# Notes: GPX Route Generator Optimization Review

## Scope and evidence limits
- Read-only review. Existing user changes remain untouched: `CLAUDE.md`, `GPX Route Generator.code-workspace`.
- Repository is single-process FastAPI + Uvicorn application. Render jobs run through in-process `BackgroundTasks`; metadata lives in a process-local `JobStore`; MP4 files live under `data/jobs`.
- GitNexus MCP does not list `GPX-Route-Generator`; no graph impact/context evidence available. Local `.gitnexus/meta.json` is stale relative to current `HEAD`, so recommendations use direct source and test inspection.
- Performance agents inspected isolated worktrees containing same application code. Their absolute worktree paths are not target paths; line references below use current checkout paths.

## Architecture and main flows
- Entry/orchestration: [app.py](src/gpx_route_generator/app.py). Routes: `/api/gpx/parse`, `/api/preview`, `/api/render`, `/api/jobs/{job_id}`, `/api/jobs/{job_id}/video`.
- Geometry: [geo.py](src/gpx_route_generator/geo.py). Resamples route to `duration_seconds * fps`, computes dynamic camera states and Web Mercator coordinates.
- Map acquisition: [maps.py](src/gpx_route_generator/maps.py) and [map_segments.py](src/gpx_route_generator/map_segments.py). At most 12 source map segments per render, fetched concurrently, retained only for one render.
- Rendering: [renderer.py](src/gpx_route_generator/renderer.py). Concurrent frame composition, ordered writes to FFmpeg raw-video stdin, Pillow overlays.
- Browser: [app.js](src/gpx_route_generator/static/app.js). Preview debounce 400 ms, aborts superseded fetches, polls job status every 1 s.
- Tests: five pytest modules cover API, geo, GPX parsing, map segments, renderer. No benchmark/load suite or coverage configuration found.

## Confirmed or high-confidence hotspots
### P0: Render startup geometry is quadratic
- [geo.py:300-308](src/gpx_route_generator/geo.py#L300-L308) scans all route samples for every camera frame through `local_route_window_points`, then rescans each window through `route_world_bounds`.
- Normal sample count equals frame count. Maximum validation allows 30 seconds × 60 FPS = 1,800 samples. This creates O(f²) work and repeated list allocations before frame rendering.
- Both [renderer.py:114-124](src/gpx_route_generator/renderer.py#L114-L124) and [preview.py:21-31](src/gpx_route_generator/preview.py#L21-L31) call this path.
- Plan: project points once; use monotonic distance-window pointers and min/max deques or an equivalent indexed rolling-window algorithm. Preserve output with golden camera-state tests; benchmark 450/900/1,800/3,600 samples.

### P0: Metric graphs rebuild complete series and geometry per frame
- [renderer.py:230-236](src/gpx_route_generator/renderer.py#L230-L236) calls `draw_metric_graphs` for every frame.
- [renderer.py:369-374](src/gpx_route_generator/renderer.py#L369-L374) rebuilds speed/elevation series each call. [renderer.py:436-480](src/gpx_route_generator/renderer.py#L436-L480) recomputes valid values, min/max, every graph point, and full polylines for every frame.
- Plan: prepare metric arrays/ranges/panel geometry once per render; cache static panel or point geometry; draw only cursor/current marker per frame. Validate pixel/output tolerance and graph marker placement.

### P0/P1: Trail redraw repeats all historical points
- [renderer.py:250-254](src/gpx_route_generator/renderer.py#L250-L254) transforms and submits every prior sample for every frame. Total work O(f²), up to about 1.62 million point transforms at 1,800 frames.
- Plan: select only points intersecting camera viewport, then screen-space decimate/retain endpoints and meaningful bends. Add visual regression tests for trail continuity and a bound on submitted points.

### P1: Preview over-computation and event-loop blocking
- [preview.py:21-32](src/gpx_route_generator/preview.py#L21-L32) resamples the full requested video frame count, computes every camera state, and builds a full segment plan although preview returns only frame zero. At current camera complexity this repeats O(f²) work on every debounced preview.
- [app.py:126-134](src/gpx_route_generator/app.py#L126-L134) makes synchronous reCAPTCHA HTTP call inside async render route.
- [app.py:198-200](src/gpx_route_generator/app.py#L198-L200) invokes synchronous parse/preview, including map I/O and Pillow, inside async preview route.
- Plan: add preview-specific frame-zero planning, then use bounded threadpool offload for remaining sync functions; use async HTTP client only if needed after measuring. Add concurrency/liveness test: slow map/reCAPTCHA must not delay config/status requests. Limit preview executor capacity.

### P1: Render resource unboundedness
- [app.py:257-267](src/gpx_route_generator/app.py#L257-L267) accepts every render, starts in-process background work, and has no queue/semaphore/cancellation.
- Each render can create map-fetch workers, frame workers, decoded images, and one FFmpeg process. Concurrent submissions multiply resource use.
- [jobs.py:40-59](src/gpx_route_generator/jobs.py#L40-L59) retains every job; no age/count/disk budget cleanup. Render outputs persist under `data/jobs`.
- Plan: establish explicit capacity (initially one or small bounded N), queue/reject policy, cancellation/shutdown cleanup, and TTL/count/total-size retention. Add disk and process/thread bound tests.

### P1: FFmpeg stderr pipe can deadlock
- [renderer.py:158-200](src/gpx_route_generator/renderer.py#L158-L200) pipes stderr but drains it only after all frame writes finish. If FFmpeg emits enough stderr to fill pipe, child blocks and parent can block writing stdin.
- Plan: drain stderr concurrently or redirect to controlled sink; preserve bounded tail for error messages. Add forced-high-stderr integration test with timeout.

### P1: Thread-safety/resource lifecycle gaps
- [maps.py:34-60](src/gpx_route_generator/maps.py#L34-L60) uses one `requests.Session` concurrently during segment prefetch. Use per-worker sessions or serialize access; close sessions in `finally`.
- [renderer.py:25,300-315](src/gpx_route_generator/renderer.py#L25-L315) has unsynchronized process-global avatar cache and returns copies after check-then-act. Add lock or immutable one-time initialization; consider bounded cache.
- [jobs.py:47-59](src/gpx_route_generator/jobs.py#L47-L59) returns mutable `RenderJob` after lock; API serializes it after lock while background thread mutates it. Return locked snapshots and expose readiness checks.

### P1: Map-provider failure policy absent
- [maps.py:31-59](src/gpx_route_generator/maps.py#L31-L59) uses one fixed 30-second timeout with no retry, backoff, or provider-wide rate control. Transient failures fail the whole render; there is no protection against broad retry storms.
- Plan: bounded retries for identified transient failures only, with jitter, attempt caps, and failure classification that never retries quota/auth/invalid-request errors.

## Medium improvements
- Speed graph depends on GPX timestamps, not `duration_seconds`: [geo.py:313-324](src/gpx_route_generator/geo.py#L313-L324) `with_elapsed_times` is unused and [models.py:44](src/gpx_route_generator/models.py#L44) `duration_seconds` does not synthesize playback times. GPX without timestamps yields a blank/`--` speed graph. Decide whether to synthesize timestamps from playback duration or label the graph as unavailable, and document behavior. Preview and render share this path.
- `/api/gpx/parse` exists at [app.py:145-161](src/gpx_route_generator/app.py#L145-L161) and returns every parsed point, but the browser UI does not call it ([app.js:105-110](src/gpx_route_generator/static/app.js#L105-L110), [app.js:247-250](src/gpx_route_generator/static/app.js#L247-L250)). Decide whether to remove it or keep it for external consumers before changing its behavior.
- Unused/near-unused helpers and dependencies inflate perceived capability: `smooth_camera_world_pixels`/`overview_camera_world_pixels` have no renderer caller ([geo.py:206-240](src/gpx_route_generator/geo.py#L206-L240)); `numpy` is declared but unused ([pyproject.toml:19](pyproject.toml#L19)).
- Requested UI zoom is not always honored: the segment planner may lower zoom to stay within the 12-image cap ([map_segments.py:58-69](src/gpx_route_generator/map_segments.py#L58-L69)). Ensure UI wording does not promise exact zoom.

- Cache font resolution by `(size, bold)`; [renderer.py:338-359](src/gpx_route_generator/renderer.py#L338-L359), [renderer.py:397-419](src/gpx_route_generator/renderer.py#L397-L419), [renderer.py:521-533](src/gpx_route_generator/renderer.py#L521-L533) perform filesystem/font loading on each frame.
- Add GPX upload byte and point-count limits before expensive parse/materialization: [app.py:148,198,253](src/gpx_route_generator/app.py#L148), [gpx.py](src/gpx_route_generator/gpx.py).
- `RenderOptions.estimated_map_requests` always reports 12 ([models.py:78-80](src/gpx_route_generator/models.py#L78-L80)) although actual plan may be 1–12; compute/report estimate from plan or label as upper bound to improve user-facing accuracy.
- Preview has browser-side debounce/abort but no server/API response cache; repeated setting changes can still consume one map request each. Add short-lived cache only after measuring duplicate request rate and define key/TTL/quota behavior.
- Per-frame full-size crop/resize/alpha composition is expected cost; benchmark before optimizing Pillow path. Consider lower preview resolution separately from final output.

## Existing good choices
- Map requests bounded by segment planner; source images reused per render.
- Frame work runs in bounded executor and writes frames in order to FFmpeg, avoiding intermediate frame files.
- Preview aborts superseded browser requests and uses sequence guard.
- Validation bounds duration, FPS, zoom, trail width, avatar size, and frame count.

## Baseline validation
- Need run current environment checks: `python3 -m pytest -q`, `python3 --version`, `ffmpeg -version`.
- Add benchmark harness before optimization. Record p50/p95 preview latency, render wall time, geometry-prep time, frame CPU time, map fetch latency/count, FFmpeg encode time, peak RSS, active jobs, and output size.
- Use representative fixtures: short/medium/long route, 5/15/30 sec, 24/60 FPS, both output formats, graph overlays on/off, mocked maps first and real Google maps only for controlled quota tests.

## Proposed sequencing
1. Instrument and establish baseline; add benchmark/fixture and output correctness snapshots.
2. Fix render correctness/reliability hazards: FFmpeg stderr drain, job snapshots, map session lifecycle, avatar-cache lock.
3. Remove O(f²) geometry/graphs/trail work; verify output and benchmark after each isolated change.
4. Protect service capacity: bounded render queue, preview executor limit, upload limits, retention cleanup, cancellation.
5. Tune map/API caching, Pillow/FFmpeg settings, worker count only from measured results.
