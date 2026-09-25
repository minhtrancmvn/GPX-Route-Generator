# GPX Route Generator Optimization Plan

## Executive decision

Optimize render computation before tuning worker counts or adding caches. Current code spends avoidable O(frame_count²) work in camera planning, graph drawing, and trail drawing. Reliability and capacity controls come first so benchmarks reflect stable behavior and production cannot exhaust threads, FFmpeg processes, memory, or disk.

Do not begin with broad rewrites. Ship one bounded change at a time, benchmark against fixed route fixtures, and compare rendered output for correctness.

## Evidence summary

| Area | Evidence | Priority |
|---|---|---:|
| Camera planning | [geo.py:300-308](src/gpx_route_generator/geo.py#L300-L308) scans route samples for every frame, then rescans each window for bounds. Current benchmark: 450 samples 0.087s, 900 0.235s, 1,800 0.559s. | P0 |
| Metric graphs | [renderer.py:230-236](src/gpx_route_generator/renderer.py#L230-L236) rebuilds series and [renderer.py:436-480](src/gpx_route_generator/renderer.py#L436-L480) rebuilds ranges/points/full lines on every frame. | P0 |
| Trail | [renderer.py:250-254](src/gpx_route_generator/renderer.py#L250-L254) transforms all historical samples for every frame. | P0 |
| FFmpeg reliability | [renderer.py:158-200](src/gpx_route_generator/renderer.py#L158-L200) drains stderr only after frame writes; full stderr can block FFmpeg and parent. | P1/blocking reliability |
| Event loop | [app.py:126-134](src/gpx_route_generator/app.py#L126-L134) and [app.py:198-200](src/gpx_route_generator/app.py#L198-L200) perform synchronous network/CPU work inside async handlers. | P1 |
| Capacity | [app.py:257-267](src/gpx_route_generator/app.py#L257-L267) accepts unlimited in-process background renders; [jobs.py:40-59](src/gpx_route_generator/jobs.py#L40-L59) retains jobs indefinitely. | P1 |
| Shared state | [maps.py:34-60](src/gpx_route_generator/maps.py#L34-L60) shares `requests.Session` across prefetch workers; [renderer.py:25,300-315](src/gpx_route_generator/renderer.py#L25-L315) has an unlocked avatar cache; [jobs.py:47-59](src/gpx_route_generator/jobs.py#L47-L59) returns mutable jobs outside lock. | P1 |
| Input/storage | GPX uploads are fully materialized; output directory currently occupies 43M across 10 MP4 files. No retention quota exists. | P1/P2 |
| Validation environment | `python3 -m pytest -q` cannot run in current environment: `No module named pytest`; Pillow also missing. `ffmpeg` is installed: 9.0.2. | Gate |

GitNexus impact analysis was unavailable because MCP registry does not contain `GPX-Route-Generator`; local index metadata is stale. Findings are source-backed and should be rechecked with graph tooling after index repair.

## Success metrics and baseline

Capture these metrics before each optimization batch:

- Preview: p50/p95 request latency, geometry-prep time, map-fetch latency, map requests per preview, response bytes.
- Render: total wall time, geometry-prep time, map-prefetch time, per-frame composition time, FFmpeg encode time, frames/second, peak RSS, output size, map request count.
- Service: active render count, queued jobs, rejected jobs, preview latency while render runs, process/thread counts, retained job count and disk usage.
- Correctness: camera-state samples, route/trail overlay snapshots, graph marker positions, output dimensions, playable MP4, completed progress and download behavior.

Use fixed fixtures:

- Short, medium, and long GPX routes.
- 5, 15, and 30 seconds; 24 and 60 FPS.
- Landscape and portrait output.
- Graph overlays enabled and disabled.
- Mocked map client for repeatable CPU benchmarks; controlled real Google requests only for quota/latency measurements.

Suggested initial acceptance targets, to be adjusted after baseline:

1. Camera preparation grows approximately linearly with sample count; 1,800 samples must not exceed 2.5× the 900-sample baseline.
2. Graph preparation occurs once per render, not once per frame.
3. Trail submitted points per frame are bounded by visible/decimated points, not frame index.
4. Slow map/reCAPTCHA calls do not block `/api/config` or job-status responses.
5. Render concurrency never exceeds configured process/thread/FFmpeg capacity.
6. Stale output cleanup keeps disk below configured budget and never deletes active jobs.

## Delivery order

### Phase 0 — Establish a reproducible benchmark gate

**Goal:** Make later speed claims trustworthy.

1. Install project dev dependencies in a clean project environment (`pytest`, Pillow, FastAPI test dependencies) without changing production behavior.
2. Add benchmark commands or a small benchmark module outside hot-path behavior. Keep mocked maps deterministic.
3. Add timing around resampling, camera planning, map prefetch, frame composition, and FFmpeg encoding. Prefer structured logs or optional instrumentation so normal output stays unchanged.
4. Record baseline results for the fixture matrix above.
5. Add output correctness checks before optimization: frame dimensions, graph/trail presence, MP4 completion, and status payload.

**Gate:** Baseline report exists; test suite passes in project environment; benchmark can be repeated with same fixtures.

### Phase 1 — Reliability and lifecycle safety

**Goal:** Prevent hangs and unsafe shared-resource behavior before performance work.

1. **Fix FFmpeg stderr handling.** Drain stderr continuously in a reader thread or redirect to a controlled sink while retaining a bounded tail for errors. Ensure stdin closes, process waits, and reader exits on both success and failure. Add a timeout test that produces enough FFmpeg stderr to fill a pipe.
2. **Return job snapshots.** Change `JobStore` read API to serialize a consistent immutable snapshot while holding lock. Avoid returning mutable `RenderJob` to route handlers. Add concurrent update/read test; video readiness check must use one consistent state.
3. **Fix map-client lifecycle.** Give concurrent map workers independent HTTP sessions, or protect session access with a lock if connection reuse is more valuable. Add explicit `close()` and invoke in render cleanup. Test concurrent prefetch and cleanup.
4. **Lock avatar cache initialization.** Guard check/build/insert; return a copy after the cache lock. Bound cache if avatar-size combinations become configurable. Test concurrent first use.
5. **Harden cleanup paths.** Ensure map images, FFmpeg process, sessions, futures, and output partial files are cleaned after exceptions.
6. **Define map-provider failure policy.** Current map fetch has one fixed 30-second timeout and no retry/backoff or provider-wide rate control. Add only bounded retries for verified transient failures, with jitter and strict attempt limits; never retry quota, authentication, or invalid-request failures. Keep retry concurrency within render admission limits.

**Gate:** No FFmpeg hang under stderr stress; concurrent job state remains internally consistent; map/session/avatar stress tests pass; transient map failures follow bounded policy; failed render leaves no live process or leaked partial resource.

### Phase 2 — Remove O(frame_count²) render work

Do each item as separate change. Benchmark and compare output after each.

#### 2A. Camera state generation

Target [geo.py:94-119](src/gpx_route_generator/geo.py#L94-L119) and [geo.py:280-310](src/gpx_route_generator/geo.py#L280-L310).

- Project route/sample coordinates once at selected zoom.
- Maintain monotonic start/end indices as frame distance increases instead of filtering all samples each frame.
- Maintain rolling x/y min/max with monotonic deques, or an equivalent indexed range-min/range-max structure.
- Preserve neighbor behavior for one-point windows and exact blend ratio.
- Keep legacy helper for small callers only if tests need it; avoid reusing it in hot loop.

**Validation:** camera output comparison on short routes; edge frames, duplicate distances, dateline-adjacent longitudes if supported; scaling benchmark.

#### 2B. Metric preprocessing

Target [renderer.py:362-480](src/gpx_route_generator/renderer.py#L362-L480).

- Build speed/elevation arrays once per render.
- Precompute valid ranges, normalized graph points, panel bounds, labels, fonts, and static grid/panel layer once.
- Per frame, draw only changing cursor/current marker and any dynamic text.
- Pass prepared immutable render assets into `_render_video_frame` and `compose_frame`.

**Validation:** graph-enabled and disabled output snapshots; missing elevation; missing GPX timestamps; constant-value series; marker at first/last frame; benchmark with 450/900/1,800 frames.

**Known behavior to decide first:** the speed series uses GPX timestamps, not playback `duration_seconds`. `with_elapsed_times` at [geo.py:313-324](src/gpx_route_generator/geo.py#L313-L324) is unused. GPX files without timestamps produce an empty speed graph. Decide whether to synthesize playback timestamps, hide the speed graph, or label it unavailable, and document the choice before optimizing this path.

#### 2C. Trail viewport selection and decimation

Target [renderer.py:240-254](src/gpx_route_generator/renderer.py#L240-L254).

- Use projected world pixels already computed.
- Select points up to current frame that can intersect current viewport, with a conservative margin for line width.
- Decimate in screen space while preserving first/last points and meaningful bends; do not discard points that cross viewport boundaries.
- Consider a per-frame visible-index range plus bounded simplification rather than a global simplifier, because camera moves.

**Validation:** trail continuity across camera movement, sharp turns, small loops, first/last frames, portrait output, and visual snapshots. Track points submitted and frame composition time.

**Gate:** Combined render wall time and peak RSS improve on representative fixtures; output remains visually acceptable; no new map request count; no correctness regressions.

### Phase 3 — Keep async service responsive and bound capacity

#### 3A. Reduce and offload blocking preview work

- Add preview-specific planning. [preview.py:21-32](src/gpx_route_generator/preview.py#L21-L32) resamples the full video frame count, computes every camera state, and builds a full segment plan although preview returns only frame zero. Compute only data required for frame-zero camera/source coverage while preserving graph inputs when enabled.
- Move remaining synchronous preview parse/render to a bounded executor or equivalent FastAPI threadpool path.
- Move synchronous reCAPTCHA verification to threadpool first; migrate to shared async HTTP client only if measurement shows thread occupancy is limiting.
- Add explicit preview concurrency limit so aborted browser requests do not create unlimited server work.
- Use separate limits for preview and final render so previews cannot starve renders.

**Validation:** inject slow map/reCAPTCHA client; call config/status concurrently; assert latency budget and no event-loop starvation.

#### 3B. Add render admission control

- Replace unlimited `BackgroundTasks` admission with a process-wide bounded queue/semaphore.
- Define behavior over capacity: return 429, or expose queued status with maximum queue length. Prefer explicit rejection over unbounded memory growth for current single-process architecture.
- Add cancellation signal support through frame futures and FFmpeg termination. Clean up on application shutdown.
- Document single-process limitation; durable queue is a separate architecture decision.

**Validation:** submit more jobs than capacity; assert bounded active FFmpeg processes, threads, memory, and clear status. Cancel queued/running job and verify cleanup.

#### 3C. Bound input and output resources

- Enforce upload byte limit before full materialization and point-count limit during parse or immediately after bounded parsing. Return clear 413/422.
- Add retention by max age, max count, and total disk budget. Never delete active jobs; clean abandoned partial jobs at startup.
- Avoid exposing raw exception text in production responses while retaining internal diagnostics.

**Validation:** oversized GPX rejection before expensive work; retention tests for age/count/size; restart cleanup test; active-job exemption.

**Gate:** concurrency/load tests show defined degradation under overload; disk and memory stay within budget; API remains responsive during render.

### Phase 4 — Tune measured secondary costs

Only after Phases 0–3:

1. Cache `load_font` by `(size, bold)`; verify filesystem loads fall to one per key.
2. Compare Pillow resize/composition strategies and preview resolution independently from final output.
3. Tune `FRAME_WORKERS` from benchmark results. More workers can worsen memory, map pressure, GIL contention, or FFmpeg backpressure.
4. Evaluate short-lived preview response/map cache only after measuring duplicate requests. Key must include route content identity, options, map credentials/provider behavior, and output mode; define TTL and quota implications.
5. Revisit persistent map cache only with explicit storage/eviction and Google Static Maps terms/quota review.
6. Correct user-facing map estimate: [models.py:78-80](src/gpx_route_generator/models.py#L78-L80) reports constant upper bound 12 while actual plan is 1–12. Keep upper-bound wording if plan construction cannot happen before response.

## Risks and trade-offs

- Rolling-window camera algorithm can alter edge behavior. Preserve existing blend and fallback semantics; compare camera-state outputs.
- Trail decimation can create visual gaps. Use conservative viewport margins and snapshot tests.
- Static graph layers reduce CPU but increase per-render memory slightly; keep assets immutable and release after render.
- Threadpool offload protects event loop but does not reduce total CPU. Capacity limits remain necessary.
- Persistent caches can increase memory/disk and create stale or incorrect output if keys omit options. Measure first.
- Lowering map requests by widening zoom may reduce API cost but reduce visual detail. Treat quality as an explicit metric.
- Current app has process-local jobs. Multi-worker deployment requires shared job state/storage or strict single-worker deployment; do not imply horizontal scaling is safe without that change.

## Recommended implementation slices

1. `perf-baseline`: benchmark harness, fixture matrix, optional instrumentation, correctness snapshots.
2. `render-reliability`: FFmpeg stderr drain, job snapshots, map session cleanup, avatar-cache lock.
3. `camera-linearization`: rolling camera-window algorithm plus geo benchmarks.
4. `render-assets`: precomputed metric graphs/fonts and prepared frame assets.
5. `trail-decimation`: viewport-aware trail preparation and visual regression coverage.
6. `service-capacity`: preview offload, render admission/cancellation, input limits, retention cleanup.
7. `perf-tuning`: measured worker/cache/Pillow/FFmpeg tuning.

Keep existing user changes in [CLAUDE.md](CLAUDE.md) and [GPX Route Generator.code-workspace](GPX%20Route%20Generator.code-workspace) separate from these slices.
