# Architecture Map

## Scope

Standard read-only exploration of GPX Route Generator, focused on architecture, render/generation flows, caching, external API calls, and performance-sensitive paths. Source inspection reflects current checkout at `/Users/coffeemug/Programming/GPX Route Generator`; application code was not modified.

## System shape

```text
Browser
  │ HTML/JS form, preview debounce, job polling
  ▼
FastAPI app (`src/gpx_route_generator/app.py`)
  ├─ GPX upload → `gpx.parse_gpx_bytes`
  ├─ options/forms → `models.RenderOptions` + validation
  ├─ preview → `preview.render_preview_frame_2d`
  └─ render → in-process FastAPI BackgroundTasks → `run_render_job`
                                      │
                                      ▼
                         geometry + segment planning
                         `geo.py` + `map_segments.py`
                                      │
                         bounded Google Static Maps fetch
                         `maps.GoogleStaticMapClient`
                                      │
                         cached source images in memory
                                      │
                         concurrent PIL frame composition
                         `renderer.py`
                                      │ raw RGB frames
                                      ▼
                         ffmpeg subprocess → `data/jobs/<id>/route.mp4`
                                      │
                                      ▼
                         `/api/jobs/{id}` + `/video`
```

## Layers and boundaries

| Layer | Location | Responsibility | Main dependencies |
|---|---|---|---|
| Presentation/API | `/Users/coffeemug/Programming/GPX Route Generator/src/gpx_route_generator/app.py` | FastAPI routes, form parsing, preview response, job lifecycle, reCAPTCHA | FastAPI, Jinja2, `gpx.py`, `renderer.py`, `preview.py` |
| Browser UI | `/Users/coffeemug/Programming/GPX Route Generator/src/gpx_route_generator/templates/index.html`, `/Users/coffeemug/Programming/GPX Route Generator/src/gpx_route_generator/static/app.js` | Upload, settings, debounced first-frame preview, render submission, one-second status polling | `/api/preview`, `/api/render`, `/api/jobs/*` |
| Domain models/config | `/Users/coffeemug/Programming/GPX Route Generator/src/gpx_route_generator/models.py`, `config.py`, `jobs.py` | Immutable route/options, dimensions, validation, environment settings, in-memory job state | Python dataclasses, `threading.Lock` |
| Route/geometry | `/Users/coffeemug/Programming/GPX Route Generator/src/gpx_route_generator/gpx.py`, `geo.py` | GPX parsing, haversine distances, distance resampling, camera states, world-pixel projection | `gpxpy`, Python math |
| Map acquisition/planning | `/Users/coffeemug/Programming/GPX Route Generator/src/gpx_route_generator/maps.py`, `map_segments.py` | HTTP map fetch, optional signing, source-image segment planning/cropping | `requests`, Pillow |
| Media rendering | `/Users/coffeemug/Programming/GPX Route Generator/src/gpx_route_generator/renderer.py`, `preview.py` | Map crop, trail/HUD/avatar composition, concurrent frames, ffmpeg streaming | Pillow, `ThreadPoolExecutor`, `subprocess` |
| Persistence/deploy | `/Users/coffeemug/Programming/GPX Route Generator/data/jobs`, `Dockerfile`, `docker-compose.yml` | Local MP4 files and container volume | filesystem, ffmpeg |

## Critical data flows

### Preview

1. Browser calls `fetch("/api/preview")` after 400 ms debounce on file/settings changes (`static/app.js:77-139`, `320-332`). Previous preview request is aborted and response sequence checked.
2. `app.py:162-207` reads upload, builds/validates options, parses GPX, creates map client, and invokes `render_preview_frame_2d`.
3. `preview.py:15-62` resamples route to `duration × fps` samples, builds camera states and a segment plan, fetches only segment 0, crops it, and composes frame 0.
4. PNG is returned. Each new preview request normally performs one external Google Static Maps request; browser cancellation does not guarantee upstream HTTP cancellation once server work starts.

### MP4 render

1. Browser posts form to `/api/render` (`static/app.js:220-266`).
2. `app.py:209-267` validates reCAPTCHA when enabled, parses GPX, creates `RenderJob`, stores it in an in-memory `JobStore`, and schedules `run_render_job` using FastAPI `BackgroundTasks`.
3. `app.py:288-318` marks job running, creates map client, and calls `renderer.render_route_video`.
4. `renderer.py:104-213` resamples points, computes camera states, plans segments, prefetches one 640×640 source image per segment using a thread pool, then composes frames concurrently while preserving output order.
5. `renderer.py:157-213` writes raw RGB frame bytes into an ffmpeg subprocess configured for H.264, `yuv420p`, and `+faststart`; output writes to `data/jobs/<job_id>/route.mp4`.
6. Progress callback updates the in-memory job after each frame. Browser polls status every 1 s (`static/app.js:276-315`) and then streams/downloads the MP4.

### Map caching and external APIs

- `maps.GoogleStaticMapClient` owns one `requests.Session` per client (`maps.py:27-59`) and applies a 30 s fetch timeout.
- Segment planning (`map_segments.py:43-70`) widens the camera only as needed to keep at most `MAX_MAP_SEGMENTS = 12` source images. The source image is fixed at `(640, 640)` with scale 2 (`map_segments.py:10-12`, `renderer.py:43-50`).
- Source images are cached only for one render invocation in a local dictionary of decoded Pillow images (`renderer.py:53-75`, `104-130`, `209-213`). No cross-job or disk/API-response cache exists.
- `RenderOptions.estimated_map_requests` always reports 12 (`models.py:78-80`), while actual segment count may be 1–12. Preview does not expose the plan count to the UI.
- reCAPTCHA adds a synchronous external POST with a 10 s timeout on render start (`app.py:117-142`).

## Performance-sensitive paths

1. External map fetch latency/cost: segment prefetch is parallelized up to `FRAME_WORKERS`, but all planned segments are fetched before ffmpeg starts (`renderer.py:53-75`, `104-130`).
2. Per-frame PIL work: every frame crops and resizes a cached high-resolution map, allocates an overlay, draws trail/HUD/graphs, rotates/composites avatar, converts to RGB, and materializes a full byte buffer (`renderer.py:78-101`, `215-236`).
3. Frame scheduling/backpressure: up to `FRAME_WORKERS` futures are queued; output writes remain ordered and block on the next frame (`renderer.py:157-198`). `process.stdin.write` can backpressure if ffmpeg encoding falls behind.
4. CPU-bound Python/Pillow concurrency: `ThreadPoolExecutor` is used for source fetch and frame composition. Effective scaling depends on Pillow/native-code behavior and ffmpeg throughput; no benchmark or worker utilization metrics exist.
5. Input scaling: `resample_by_distance` and several geometry helpers repeatedly traverse route/sample lists (`geo.py:144-193`, `renderer.py:564-568`). `draw_metric_graph` scans full metric series per frame to compute min/max (`renderer.py:435-447`), adding avoidable O(frames × samples) work for graph-enabled renders.
6. Preview churn: every qualifying browser input change triggers a debounced server render path and one map request (`static/app.js:320-332`, `app.py:162-207`), with no client result cache or server map cache.
7. Output storage: jobs are written to local disk and retained; ten existing sample outputs consume about 44.7 MB in `data/jobs`, with no TTL, cleanup, quota, or persisted job metadata.

## Deployment/runtime constraints

- `Dockerfile` runs one Uvicorn process and installs ffmpeg; `docker-compose.yml` sets `FRAME_WORKERS: 4` and bind-mounts `./data`.
- Render execution is in-process `BackgroundTasks`, not a durable queue. Restart loses job state and queued work; multiple workers/processes do not share `JobStore`.
- `Settings.jobs_dir` is based on `Path.cwd()` (`config.py:28-39`), so launch directory controls output location.
- Tests cover route math, segment planning, frame composition, API validation, mocked map requests, and one ffmpeg integration path. No performance benchmark, load test, real Google API test, or browser E2E harness appears in repository.

## Index note

Project `CLAUDE.md` identifies GitNexus repo `GPX-Route-Generator`, but configured GitNexus MCP currently lists only `atk-automation-test`, `Task-Automation`, and `OOLE-waybill_generator`; requested repository context/query calls therefore could not run. Local `.gitnexus/meta.json` is stale relative to current `HEAD` (indexed commit `0e64c39`, current `HEAD` `06bbb64`). `npx gitnexus analyze` was attempted with a temporary npm cache but did not refresh metadata in this checkout.
