# Render Path Optimizations — Design

Date: 2026-09-30
Branch: `perf/render-path-optimizations`
Status: Approved for planning

## Goal

Reduce repeated render computation in three isolated slices while preserving visual behavior and keeping each performance gain measurable.

## Constraints

- Implement in this order: graph preprocessing, camera linearization, trail culling/decimation.
- Each slice receives its own impact analysis, tests, benchmark comparison, commit, review, and merge gate.
- No Docker work.
- Preserve unrelated `CLAUDE.md` and workspace changes.
- Do not combine slices. A regression or benchmark change must remain attributable to one optimization.

## Slice 1 — Metric graph preprocessing

### Behavior

- Hide speed graph when GPX timestamps are unavailable.
- Hide elevation graph when elevation values are unavailable.
- Draw no graph panel when neither series is available.
- Do not synthesize speed or elevation values.
- Preserve current graph colors, placement, labels, cursor, and marker behavior.

### Design

Prepare immutable graph assets once per preview/render:

- speed/elevation series
- valid ranges
- normalized graph points
- labels and fonts
- static panel, grid, and line layer

Each frame draws only changing cursor/current marker state over the static graph layer.

### Verification

- missing timestamps/elevation
- constant series
- gaps (`None`)
- first and last markers
- landscape and portrait output checks
- 450/900/1,800-frame benchmark before and after

## Slice 2 — Camera planning linearization

### Behavior

- Preserve current zoom selection.
- Preserve exact 45% route-window / 55% current-point center blend.
- Preserve one-point-window behavior and edge frames.
- Antimeridian behavior is outside this optimization.

### Design

- project route points once
- use monotonic start/end distance-window indices
- maintain range extrema incrementally or through an indexed range query
- avoid rebuilding/scanning the entire route window for each frame

Target complexity: O(N) or O(N log N), replacing current O(N²) behavior.

### Verification

- golden camera states from current implementation
- duplicate distances
- short routes
- first/last frames
- scaling target: 1,800-frame planning time no more than 2.5× 900-frame time

## Slice 3 — Trail viewport culling and decimation

### Behavior

- Preserve current and endpoint positions exactly.
- No visible gaps at normal playback size.
- At most one-pixel deviation for retained straight segments.
- Preserve sharp turns, small loops, and viewport crossings.

### Design

- cull points outside viewport plus conservative line-width margin
- decimate nearly collinear points in screen space
- retain first visible point, latest point, viewport crossings, and meaningful bends
- apply per frame because camera position changes
- do not globally simplify the route

### Verification

- turns, loops, viewport entry/exit
- first/last frames
- portrait/landscape snapshots
- bound submitted trail-point count
- benchmark frame-composition time before and after

## Delivery gate

Each slice must:

1. pass GitNexus impact analysis before edits
2. add failing correctness tests first
3. record before/after benchmark data
4. pass focused and full test suites
5. run GitNexus change detection before commit
6. receive code review
7. merge before the next slice begins
