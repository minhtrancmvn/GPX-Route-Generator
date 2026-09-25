# Codebase Exploration Report

## Executive Summary

GPX Route Generator is a single-process FastAPI application that accepts GPX uploads, plans a bounded set of Google Static Maps images, composes route animation frames with Pillow, and streams raw frames to FFmpeg for MP4 output. Browser JavaScript owns debounced previews and job polling; job metadata remains process-local and video files remain under `data/jobs`.

System is coherent for local use and has good bounded map-source reuse, but lacks production capacity controls and measurement. Highest-impact issues are repeated O(frame_count²) camera/trail/graph work, blocking sync work in async handlers, delayed FFmpeg stderr draining, mutable shared job/cache state, and indefinite output retention.

## Quick Facts

- Language: Python 3.11+; vanilla JavaScript/CSS.
- Framework: FastAPI, Uvicorn, Jinja2, Pillow, gpxpy, requests, FFmpeg.
- Architecture: single-process layered application with in-process background jobs.
- Test strategy: pytest unit tests plus API tests, mocked map client, and one FFmpeg integration path.
- Deployment: Docker/Compose; one Uvicorn process; bind-mounted `data` volume.
- Graph status: GitNexus repository unavailable in configured registry; direct source inspection used.

## Architecture Overview

```text
Browser UI
  -> FastAPI routes (`app.py`)
      -> GPX parsing/options (`gpx.py`, `models.py`)
      -> geometry/camera (`geo.py`)
      -> map segment planning/fetch (`map_segments.py`, `maps.py`)
      -> Pillow frame composition (`preview.py`, `renderer.py`)
      -> FFmpeg subprocess -> data/jobs/<job_id>/route.mp4
      -> JobStore status (`jobs.py`) -> browser polling/download
```

| Layer | Files | Responsibility |
|---|---|---|
| Presentation/API | `src/gpx_route_generator/app.py`, `templates/index.html` | Routes, forms, preview, render admission, job/video endpoints |
| Browser | `src/gpx_route_generator/static/app.js`, `styles.css` | Upload, debounce/abort preview, render submit, polling |
| Domain/config | `models.py`, `config.py`, `jobs.py` | Immutable route/options, validation, environment settings, process-local jobs |
| Geometry | `gpx.py`, `geo.py` | GPX parsing, distances, resampling, camera states, projection |
| Maps | `maps.py`, `map_segments.py` | Google fetch/signing, source segment planning, crop bounds |
| Rendering | `preview.py`, `renderer.py` | Frame overlays, concurrent composition, FFmpeg streaming |
| Deployment | `Dockerfile`, `docker-compose.yml`, `data/jobs` | FFmpeg image, runtime process, local output persistence |

## Key Components

### API and job orchestration
- Purpose: validate requests, parse uploaded GPX, create jobs, run render tasks, expose status/video.
- Location: `/Users/coffeemug/Programming/GPX Route Generator/src/gpx_route_generator/app.py`.
- Dependencies: FastAPI, `requests`, GPX parser, preview/renderer, `JobStore`.
- Dependents: browser calls `/api/preview`, `/api/render`, `/api/jobs/*`.
- Important constraint: `BackgroundTasks` is in-process; restart loses queued work and job state.

### Geometry
- Purpose: turn route points into frame samples and camera states.
- Location: `gpx.py`, `geo.py`.
- Dependencies: standard-library math/datetime and immutable `RoutePoint`.
- Dependents: preview and final renderer.
- Hotspot: `dynamic_camera_states` repeatedly filters/rescans route windows (`geo.py:300-308`).

### Map planning and acquisition
- Purpose: keep source map request count at most 12 and crop reusable sources.
- Location: `map_segments.py`, `maps.py`.
- Dependencies: Pillow, `requests`, Google Static Maps API.
- Dependents: preview and final renderer.
- Good choice: source images are reused within one render, avoiding one request per frame.

### Renderer
- Purpose: compose overlays and encode MP4.
- Location: `renderer.py`, `preview.py`.
- Dependencies: Pillow, `ThreadPoolExecutor`, subprocess FFmpeg.
- Dependents: API render job and preview route.
- Hotspots: trail and graph redraw; stderr pipe lifecycle; unlocked avatar cache.

### Job store
- Purpose: hold status/progress/error metadata.
- Location: `jobs.py`.
- Dependencies: `threading.Lock`, dataclasses, filesystem path values.
- Dependents: API status/video routes and render callback.
- Gap: `get` returns mutable `RenderJob` after releasing lock.

### Tests and deployment
- Tests: `tests/test_api.py`, `test_geo.py`, `test_gpx.py`, `test_map_segments.py`, `test_renderer.py`.
- Deployment: `Dockerfile`, `docker-compose.yml`, `scripts/dev.sh`.
- Missing: CI, benchmark/load suite, browser E2E, health checks, retention tests.

## Patterns and Conventions

- Immutable domain objects: frozen dataclasses in `models.py`.
- Explicit validation: `ValueError` from model and GPX validation translated to HTTP 422 by API routes.
- In-process concurrency: FastAPI `BackgroundTasks` plus thread pools for map/frame work.
- Bounded source acquisition: `MAX_MAP_SEGMENTS = 12` and per-render image reuse.
- Browser resilience: 400 ms debounce, `AbortController`, sequence guard, one-second polling.
- Error conversion: expected parse/validation failures are user-readable; unexpected preview errors currently expose `str(exc)`.
- Configuration: environment variables loaded by `config.py`; output location derives from `Path.cwd()`.

## Critical Paths

### Preview

`static/app.js:82-139` -> `POST /api/preview` (`app.py:163-208`) -> upload read and `parse_gpx_bytes` -> `render_preview_frame_2d` (`preview.py:16-63`) -> full sample/camera/segment planning -> one map fetch -> crop and overlay -> PNG response.

Preview returns frame zero but currently computes the full requested sample/camera plan. Browser aborts superseded requests, but server-side work already started can continue.

### Final MP4 render

`static/app.js:221-267` -> `POST /api/render` (`app.py:210-268`) -> options/GPX validation -> `JobStore.add` -> in-process `BackgroundTasks` -> `run_render_job` -> `render_route_video` (`renderer.py:105-213`) -> map prefetch -> concurrent frame composition -> ordered FFmpeg stdin writes -> status polling/video download.

### Map source reuse

Camera states -> `build_map_segment_plan` (`map_segments.py:44-71`) -> 1–12 segments -> concurrent `StaticMapClient.fetch` calls -> decoded source images -> per-frame crop/resize. `RenderOptions.estimated_map_requests` still reports 12 regardless of actual plan size (`models.py:78-80`).

## Deep Quality Assessment

1. **Critical performance:** camera preparation is quadratic in sample/frame count (`geo.py:300-308`).
2. **High performance:** graph series and geometry rebuild each frame (`renderer.py:362-480`); trail transforms all historical samples (`renderer.py:240-254`).
3. **High reliability:** FFmpeg stderr is drained only after all frame writes (`renderer.py:158-203`), allowing pipe backpressure deadlock.
4. **High capacity:** every render is admitted and jobs/output persist without bounded queue or retention (`app.py:257-267`, `jobs.py:38-59`).
5. **High availability:** synchronous reCAPTCHA, parsing, Pillow, and preview work execute inside async routes (`app.py:126-134`, `198-200`, `232-267`).
6. **High concurrency:** shared requests session and check-then-act avatar cache are not protected (`maps.py:31-60`, `renderer.py:299-315`).
7. **Medium safety:** upload bytes and GPX point count are not capped before materialization (`app.py:148`, `198`, `253`; `gpx.py:12-38`).
8. **Medium security/quality:** raw unexpected exception text is returned by preview endpoint (`app.py:201-204`).

## Recommended sequence

1. Establish repeatable baseline: fixture matrix, timings, peak RSS, map requests, output checks.
2. Fix reliability first: continuously drain FFmpeg stderr, return immutable job snapshots, fix map session lifecycle, lock avatar cache, clean partial resources.
3. Linearize camera preparation; compare camera states and edge behavior against golden fixtures.
4. Prepare static graph assets once per render; then add viewport-aware trail selection/decimation with visual snapshots.
5. Protect service capacity: preview executor limits, bounded render admission, cancellation, upload limits, retention cleanup.
6. Tune fonts, Pillow, worker count, and short-lived preview caching only after measurement.

## Next Steps for Understanding

1. Read `src/gpx_route_generator/app.py` and `renderer.py` together to trace API-to-FFmpeg lifecycle.
2. Trace `geo.dynamic_camera_states` into `map_segments.build_map_segment_plan` before changing camera behavior.
3. Read `tests/test_api.py` and `tests/test_renderer.py` to understand current correctness assumptions.
4. Repair GitNexus indexing, then rerun impact/process queries before editing symbols.
5. Add benchmark and concurrency fixtures before implementing optimization slices.

## Verification Record

- `.venv/bin/python -m pytest -q`: passed; one Starlette/httpx deprecation warning.
- `.venv/bin/python -m pip check`: passed.
- Python `3.14.6`; FFmpeg `9.0.2`.
- Existing application files were not modified.
- Existing user changes in `CLAUDE.md` and `GPX Route Generator.code-workspace` were preserved.
