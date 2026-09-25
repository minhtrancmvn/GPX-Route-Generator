# Deep Exploration Analysis Compilation

## Scope and evidence

Read-only assessment of `/Users/coffeemug/Programming/GPX Route Generator`. Application source, tests, deployment files, browser code, existing architecture notes, and current runtime checks were inspected. No application code was changed. Existing working-tree changes were preserved.

GitNexus graph analysis could not run: configured MCP registry does not contain `GPX-Route-Generator`; it reports only `atk-automation-test`, `Task-Automation`, and `OOLE-waybill_generator`. Findings are source-backed and line-referenced.

## Component comparison matrix

| Component | Consistency | Quality | Coverage | Dominant pattern | Outlier / root cause |
|---|---:|---:|---:|---|---|
| FastAPI/API (`src/gpx_route_generator/app.py`) | Mixed | Medium | Medium | Async routes call synchronous parse, Pillow, HTTP, and render-planning code | Feature additions lack one execution-boundary policy |
| Browser UI (`src/gpx_route_generator/static/app.js`) | High | Medium | Low | Debounced preview, abort controller, sequence guard, one-second polling | No browser E2E tests; cancellation cannot stop server work already started |
| Models/config (`models.py`, `config.py`) | High | Medium | Medium | Frozen dataclasses and environment-driven settings | Fixed map estimate; cwd-dependent jobs path |
| GPX/geometry (`gpx.py`, `geo.py`) | High | Medium | Medium | Pure functions, immutable route points, list transformations | Camera planning repeatedly scans all samples |
| Map planning/client (`map_segments.py`, `maps.py`) | Medium | Medium | Medium | Bounded per-render segment plan and concurrent prefetch | Shared `requests.Session`; no explicit close or retry policy |
| Rendering (`renderer.py`, `preview.py`) | Medium | Medium-low | Medium | PIL composition, bounded pool, ordered FFmpeg writes | Per-frame graph/trail recomputation; delayed stderr drain; unlocked avatar cache |
| Job lifecycle (`jobs.py`, `app.py`) | Low | Low | Low | In-process `BackgroundTasks` and process-local dictionary | Mutable state escapes lock; no capacity, cancellation, TTL, or disk budget |
| Deployment (`Dockerfile`, `docker-compose.yml`) | Medium | Medium | Low | Single Uvicorn process, local volume, installed FFmpeg | No durable queue/state, CI, health, or load validation |
| Tests (`tests/*.py`) | High | Medium | Medium-low | Pytest unit/API tests with mocked maps and one FFmpeg integration path | No benchmark, load, browser, concurrency, or retention tests |

## Evaluation dimensions

### Consistency

**64% (7/11 reviewed concerns follow coherent patterns).** Consistent patterns include frozen domain dataclasses (`models.py:34-56`), pure geometry helpers, explicit `ValueError` validation (`models.py:83-100`, `gpx.py:12-38`), bounded map segments (`map_segments.py:11`, `44-71`), and browser request sequencing (`static/app.js:78-139`). Outliers are blocking work inside async routes (`app.py:118-143`, `198-200`, `232-267`), mutable job reads (`jobs.py:47-59`), incomplete resource lifecycle, and fixed map estimates (`models.py:78-80`, `static/app.js:142-144`).

### Quality

**58% (7/12 major areas acceptable for local use).** Good choices include capped/reused map sources, ordered FFmpeg writes, bounded option validation, deterministic mocked-map tests, and streamed output. Gaps include quadratic camera/trail/graph work, unbounded render/job resources, possible FFmpeg pipe deadlock, shared mutable state, blocking external calls, and raw preview exception text (`app.py:201-204`).

### Coverage

**45% (5/11 major behavior areas have direct tests).** Tests cover API validation/preview/render smoke behavior, geometry, GPX parsing, map planning, and frame overlays. Missing coverage includes event-loop liveness, FFmpeg stderr pressure, concurrent job reads, map session lifecycle, avatar-cache races, input/resource limits, retention, cancellation, browser flows, benchmarks, and deployment health.

### Operational readiness

**38% (3/8 production safeguards present).** Present: FFmpeg in Docker, Compose restart policy, optional reCAPTCHA, configurable frame workers. Missing: bounded admission, durable queue/state, cancellation, startup cleanup, disk quotas, upload limits, health/readiness checks, CI, and telemetry.

## Verified findings and root causes

| Rank | Finding | Evidence | Severity | Root cause | Fix complexity |
|---:|---|---|---|---|---|
| 1 | Camera planning scans route windows for every frame and rescans each window for bounds | `src/gpx_route_generator/geo.py:300-308` | Critical performance | List implementation retained in hot path as frame count grew | Significant algorithm change plus golden-output tests |
| 2 | Metric graph series, ranges, geometry, and polylines rebuild per frame | `src/gpx_route_generator/renderer.py:230-236`, `362-480` | High performance | Static graph preparation coupled to frame drawing | Moderate asset-preparation refactor |
| 3 | Trail transforms every historical sample on every frame | `src/gpx_route_generator/renderer.py:240-254` | High performance | No viewport selection or screen-space decimation | Moderate visual-preserving change |
| 4 | FFmpeg stderr is not drained while frame writes are active | `src/gpx_route_generator/renderer.py:158-203` | High reliability | Stderr treated as post-run diagnostics | Moderate process-lifecycle fix and stress test |
| 5 | Render admission and output/job retention are unbounded | `src/gpx_route_generator/app.py:257-267`, `src/gpx_route_generator/jobs.py:38-59` | High reliability | Prototype uses BackgroundTasks and memory state without capacity policy | Moderate service policy and cleanup |
| 6 | Blocking HTTP/CPU work runs inside async endpoints | `src/gpx_route_generator/app.py:126-134`, `198-200`, `232-267` | High availability | Sync libraries called directly from route handlers | Moderate executor/offload change |
| 7 | Shared map session and unlocked avatar cache have concurrency hazards | `src/gpx_route_generator/maps.py:31-60`, `src/gpx_route_generator/renderer.py:299-315` | High reliability | Thread pools added around stateful objects without lifecycle/lock abstraction | Low-to-moderate |
| 8 | Uploads are fully materialized without explicit byte/count caps | `src/gpx_route_generator/app.py:148`, `198`, `253`; `src/gpx_route_generator/gpx.py:12-38` | Medium capacity/safety | Option validation does not constrain input size | Low-to-moderate |
| 9 | Preview errors expose raw exception text | `src/gpx_route_generator/app.py:201-204` | Medium security/quality | Local debugging path forwarded exception text | Low |
| 10 | No benchmark, load, browser, concurrency, or retention suite | `pyproject.toml:23-37`; `tests/*.py` | Medium quality | Tests grew around feature behavior, not operational limits | Moderate |

## Intentional vs accidental deviations

Intentional local constraints: one-process deployment, per-render map reuse, north-up 2D output, and process-local MP4 storage are documented in `README.md:114-121`, `Dockerfile:23-26`, and `docker-compose.yml:1-13`.

Likely accidental drift: blocking calls in async handlers, fixed map estimate, mutable job escape, unbounded retention, missing session close, and per-frame static graph work. No source documentation justifies these deviations.

## Validation evidence

- `.venv/bin/python -m pytest -q`: passed; output contained one Starlette/httpx deprecation warning.
- `.venv/bin/python -m pip check`: passed with `No broken requirements found.`
- Python `3.14.6`; FFmpeg `9.0.2`.
- `data/jobs`: approximately `43M`, `10` MP4 files at inspection time.
- No coverage configuration, benchmark module, CI workflow, browser E2E harness, or load-test directory found.
