# Render Path Optimizations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove repeated metric, camera, and trail computation while preserving current render appearance and recording attributable performance gains.

**Architecture:** Execute three isolated slices in order. Each slice starts from a green merged branch, adds correctness tests before implementation, records before/after benchmark results, runs GitNexus impact/change gates, receives review, and merges before the next slice starts.

**Tech Stack:** Python 3.11+, Pillow, pytest, standard-library timing/data structures, GitNexus.

**Spec:** `docs/superpowers/specs/2026-09-30-render-path-optimizations-design.md`

## Global Constraints

- Order is fixed: graph preprocessing, camera linearization, trail culling/decimation.
- Do not combine slices in one commit or branch.
- Preserve current graph colors, placement, labels, cursor, and marker behavior.
- Hide speed graph when timestamps are unavailable; hide elevation graph when elevations are unavailable.
- Do not synthesize metric values.
- Preserve camera zoom and exact 45% window / 55% point center blend.
- Antimeridian behavior is out of scope.
- Preserve trail endpoints, latest point, viewport crossings, sharp turns, and loops.
- Maximum one-pixel deviation for decimated straight segments.
- No Docker work.
- Preserve unrelated `CLAUDE.md` and workspace changes.
- Run GitNexus impact before every production-symbol edit and detect changes before every commit.
- `docs/deferred-production-roadmap.md` is complete and must remain unchanged unless factual corrections are required.

## Review Focus

- Timestamp-less and elevation-less GPX must not draw empty graph panels.
- Constant and gapped metric series must produce stable geometry without division errors or connecting gaps.
- Duplicate route distances must not break camera-window progression or golden-state equality.
- Trail segments entering/exiting the viewport must not disappear at boundaries.
- Portrait and landscape renders must keep graph/trail layout within one-pixel visual tolerance.

---

### Task 1: Precompute Metric Graph Assets

**Files:**
- Modify: `src/gpx_route_generator/renderer.py`
- Modify: `src/gpx_route_generator/preview.py`
- Create: `tests/test_metric_preparation.py`
- Modify: `tests/test_renderer.py`
- Create or modify: `benchmarks/benchmark_metrics.py`
- Modify: `docs/performance-baseline.md`

**Interfaces:**
- Produces `PreparedMetricGraphs`, an immutable object containing available series, ranges, static geometry/layer, and fonts.
- Produces `prepare_metric_graphs(samples, sample_distances, options) -> PreparedMetricGraphs | None`.
- `compose_frame` consumes optional prepared graphs and draws only cursor/current markers per frame.

- [ ] **Step 1: Run GitNexus impact**

Analyze upstream impact for `draw_metric_graphs`, `draw_metric_graph`, `compose_frame`, `render_route_video`, and `render_preview_frame_2d`. Record direct callers, affected processes, and risk before editing.

- [ ] **Step 2: Add behavior tests before implementation**

Create tests asserting:

```python
def test_prepare_metrics_hides_speed_without_timestamps(): ...
def test_prepare_metrics_hides_elevation_without_values(): ...
def test_prepare_metrics_returns_none_when_no_series_available(): ...
def test_prepare_metrics_handles_constant_and_gapped_series(): ...
def test_prepared_graph_marker_matches_first_and_last_frame(): ...
```

Add landscape/portrait pixel assertions using deterministic samples and existing mocked map behavior.

- [ ] **Step 3: Verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_metric_preparation.py tests/test_renderer.py -q
```

Expected: failures because preparation interfaces do not exist and current code draws unavailable panels.

- [ ] **Step 4: Capture before benchmark**

Implement only the benchmark harness needed to invoke existing graph drawing at 450/900/1,800 frames with graphs enabled. Save raw before values in `docs/performance-baseline.md`.

- [ ] **Step 5: Implement immutable prepared graph assets**

Add frozen dataclasses for prepared series/geometry. Compute series, valid ranges, normalized point segments, fonts, and static panel/grid/line layer once. Return `None` when no graph is available.

Pass prepared assets through preview/render frame composition. Draw only cursor/current marker per frame. Do not modify graph palette or layout formulas.

- [ ] **Step 6: Verify correctness and benchmark**

Run:

```bash
.venv/bin/python -m pytest tests/test_metric_preparation.py tests/test_renderer.py tests/test_api.py -q
.venv/bin/python -m benchmarks.benchmark_metrics --frames 450
.venv/bin/python -m benchmarks.benchmark_metrics --frames 900
.venv/bin/python -m benchmarks.benchmark_metrics --frames 1800
.venv/bin/python -m pytest -q
```

Record before/after timings and environment in `docs/performance-baseline.md`.

- [ ] **Step 7: Detect changes, review, and commit**

Run GitNexus detect-changes against task base. Review visual/correctness and benchmark evidence. Commit only Task 1 files:

```bash
git commit -m "perf: precompute metric graph assets"
```

Merge Task 1 branch and verify full suite before Task 2.

---

### Task 2: Linearize Camera Planning

**Files:**
- Modify: `src/gpx_route_generator/geo.py`
- Create: `tests/test_camera_golden.py`
- Modify: `tests/test_geo.py`
- Modify: `benchmarks/benchmark_geometry.py`
- Modify: `docs/performance-baseline.md`

**Interfaces:**
- Preserve `dynamic_camera_states(...) -> list[CameraState]` signature.
- Internal indexed-window helpers remain private to `geo.py`.

- [ ] **Step 1: Run GitNexus impact**

Analyze `dynamic_camera_states`, `local_route_window_points`, `route_center_world_pixel`, preview, and render callers. Warn on HIGH/CRITICAL before edits.

- [ ] **Step 2: Capture golden outputs from current implementation**

Create deterministic fixtures for normal route, duplicate distances, short route, and first/last windows. Store expected zoom and center coordinates with strict floating tolerance:

```python
assert actual.zoom == expected.zoom
assert actual.center_world == pytest.approx(expected.center_world, abs=1e-9)
```

- [ ] **Step 3: Verify goldens pass before optimization**

Run:

```bash
.venv/bin/python -m pytest tests/test_camera_golden.py tests/test_geo.py -q
```

Expected: PASS against current algorithm. Temporarily mutate one expected center locally to confirm test fails, then restore it before implementation.

- [ ] **Step 4: Record fresh before benchmark**

Run geometry benchmark at 450/900/1,800 frames and record current values in the baseline doc.

- [ ] **Step 5: Implement indexed moving windows**

Preproject points once. Advance monotonic left/right indices against cumulative distances. Use an indexed range-min/range-max query or monotonic deques to obtain exact world-pixel bounds without rescanning windows. Preserve fallback/neighbor behavior and blend arithmetic.

- [ ] **Step 6: Verify exact behavior and scaling**

Run:

```bash
.venv/bin/python -m pytest tests/test_camera_golden.py tests/test_geo.py tests/test_map_segments.py tests/test_renderer.py -q
.venv/bin/python -m benchmarks.benchmark_geometry --point-count 900 --sample-count 900 --repeats 5
.venv/bin/python -m benchmarks.benchmark_geometry --point-count 1800 --sample-count 1800 --repeats 5
.venv/bin/python -m pytest -q
```

Acceptance: golden outputs pass and 1,800-frame camera time is no more than 2.5× 900-frame time.

- [ ] **Step 7: Detect changes, review, and commit**

Run GitNexus detect-changes. Review correctness and scaling. Commit:

```bash
git commit -m "perf: linearize dynamic camera planning"
```

Merge Task 2 and verify full suite before Task 3.

---

### Task 3: Cull and Decimate Trail Geometry

**Files:**
- Modify: `src/gpx_route_generator/renderer.py`
- Create: `tests/test_trail_geometry.py`
- Modify: `tests/test_renderer.py`
- Create: `benchmarks/benchmark_trail.py`
- Modify: `docs/performance-baseline.md`

**Interfaces:**
- Produces private `visible_trail_points(...) -> list[tuple[float, float]]` returning ordered screen-space points.
- `draw_trail` consumes prepared visible points without changing public renderer APIs.

- [ ] **Step 1: Run GitNexus impact**

Analyze `draw_trail`, `world_to_frame`, `compose_frame`, and render/preview processes.

- [ ] **Step 2: Add trail correctness tests before implementation**

Cover:

```python
def test_visible_trail_preserves_first_latest_and_crossings(): ...
def test_trail_decimation_preserves_sharp_turns_and_loops(): ...
def test_straight_segment_deviation_is_at_most_one_pixel(): ...
def test_trail_margin_prevents_viewport_edge_gaps(): ...
def test_portrait_and_landscape_trails_match_reference_pixels(): ...
```

Add submitted-point count assertion for a long nearly straight route.

- [ ] **Step 3: Verify RED and capture before benchmark**

Run focused tests and record current 450/900/1,800-frame composition timings and point counts.

- [ ] **Step 4: Implement conservative viewport selection**

Transform points through current camera/options. Retain segments intersecting viewport expanded by line-width margin. Include predecessor/successor points around crossings so lines remain continuous.

- [ ] **Step 5: Implement screen-space decimation**

Remove only nearly collinear intermediate points whose perpendicular deviation is at most one pixel. Always retain first visible point, latest point, viewport crossings, and sharp turns. Keep ordering stable.

- [ ] **Step 6: Verify visual behavior and benchmark**

Run:

```bash
.venv/bin/python -m pytest tests/test_trail_geometry.py tests/test_renderer.py tests/test_api.py -q
.venv/bin/python -m benchmarks.benchmark_trail --frames 450
.venv/bin/python -m benchmarks.benchmark_trail --frames 900
.venv/bin/python -m benchmarks.benchmark_trail --frames 1800
.venv/bin/python -m pytest -q
```

Record timings, submitted-point counts, and environment in baseline doc.

- [ ] **Step 7: Detect changes, review, and commit**

Run GitNexus detect-changes and visual review. Commit:

```bash
git commit -m "perf: cull and decimate trail geometry"
```

Merge Task 3 and run final branch verification.

---

### Task 4: Final Verification and Deferred Roadmap Check

**Files:**
- Verify: `docs/deferred-production-roadmap.md`
- Verify: `docs/performance-baseline.md`
- Verify: all source/tests/benchmarks changed by Tasks 1–3

- [ ] **Step 1: Verify deferred roadmap completeness**

Confirm Browser E2E, durable DB/queue, and dashboards each contain trigger conditions, smallest viable implementation, and non-goals.

- [ ] **Step 2: Run final verification**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests benchmarks
.venv/bin/python -m pip check
```

Run fatal Ruff checks on changed files. Do not run Docker.

- [ ] **Step 3: Run final GitNexus detection and whole-range review**

Compare from the pre-optimization base to final HEAD. Review affected preview/render flows, visual behavior, and benchmark claims.

- [ ] **Step 4: Confirm repository state**

Ensure only unrelated pre-existing `CLAUDE.md` and workspace modifications remain. Remove completed agent worktrees and prune registrations.

## Plan Self-Review

- Spec coverage: all three optimization slices and deferred roadmap verification are assigned.
- Placeholder scan: no TBD/TODO or unspecified implementation steps.
- Type consistency: prepared graph and visible-trail interfaces are introduced before consumers.
- Review-focus coverage: unavailable metrics, gapped/constant series, duplicate distances, viewport crossings, and both formats have explicit tests.
