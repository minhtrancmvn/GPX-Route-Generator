# Performance Baseline

Generated on 2026-09-24 from branch `perf-baseline`.

## Scope

Measurement-only baseline for geometry preparation. No production behavior or
rendering algorithm changed. Map requests are not made; benchmark uses synthetic
`RoutePoint` fixtures and pure geometry functions.

## Repeatable command

Run from repository root:

```bash
.venv/bin/python -m benchmarks.benchmark_geometry \
  --point-count 1800 \
  --sample-count 1800 \
  --repeats 3
```

The command emits JSON with Python/platform, input sizes, median stage timings,
and correctness counts. Re-run after geometry optimization and compare the same
parameters on the same machine/runtime.

Run the mocked-map preview baseline separately:

```bash
.venv/bin/python -m benchmarks.benchmark_preview \
  --point-count 1800 \
  --sample-count 1800
```

This performs no Google API calls. It reports preview wall time, output size,
dimensions, and map-client request count.

## Baseline matrix

Environment:

- Python 3.14.6
- macOS 27.0 arm64
- 3 repeats per case; median reported
- Synthetic route: monotonic latitude/longitude/elevation changes

| Route points | Samples | cumulative distances (s) | resample (s) | camera states (s) |
|---:|---:|---:|---:|---:|
| 450 | 450 | 0.000211 | 0.000684 | 0.021640 |
| 900 | 900 | 0.000431 | 0.001312 | 0.059454 |
| 1,800 | 1,800 | 0.000775 | 0.002640 | 0.215358 |

## Dynamic camera planning — Task 2

Measured on 2026-09-30, macOS 27.0 arm64, Python 3.14.6. Both measurements use deterministic synthetic routes, five repeats per case, and report median stage times. Camera golden tests retain normal, duplicate-distance, short-route, first/last-window, sparse-window fallback, and single-point fallback behavior.

| Samples | Camera before (s) | Camera after (s) | Change |
|---:|---:|---:|---:|
| 450 | 0.020300 | 0.000724 | -96.43% |
| 900 | 0.049604 | 0.001349 | -97.28% |
| 1,800 | 0.185640 | 0.002715 | -98.54% |

The optimized 1,800-sample camera time is 2.01x the 900-sample time, below the 2.5x acceptance limit. Preprojected world pixels and monotonic min/max deques retain exact legacy-window bounds in linear time. Antimeridian handling remains out of scope.

Mocked-map preview baseline:

| Route points | Samples | Preview (s) | Map requests | PNG bytes |
|---:|---:|---:|---:|---:|
| 450 | 450 | 0.146307 | 1 | 10,184 |
| 900 | 900 | 0.414392 | 1 | 6,612 |
| 1,800 | 1,800 | 1.494015 | 1 | 6,612 |

Values are baseline observations, not acceptance thresholds. Camera preparation
is the dominant measured geometry stage and grows superlinearly across this
matrix, matching the source review's O(sample_count²) finding. Preview also
grows superlinearly while map requests remain fixed at one.

## Metric graph preparation — Task 1

Measured on 2026-09-30, macOS 27.0 arm64, Python 3.14.6. `--unprepared` uses legacy per-frame graph work; default reuses `PreparedMetricGraphs`. Both modes rendered two graphs for requested frame counts and produced byte-identical final PNG frames.

### Whole-frame render loop

This benchmark includes map-image copying, trail drawing, avatar drawing, graph rendering, and final image composition. It measures end-to-end frame work, not isolated graph cost.

```bash
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 450 --unprepared
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 900 --unprepared
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 1800 --unprepared
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 450
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 900
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 1800
```

| Frames | Legacy whole-frame (s) | Prepared assets (s) | Prepared whole-frame (s) | Loop change |
|---:|---:|---:|---:|---:|
| 450 | 1.485014 | 0.003017 | 1.236942 | -16.71% |
| 900 | 4.012363 | 0.003485 | 2.921558 | -27.19% |
| 1,800 | 11.642951 | 0.004091 | 7.567435 | -35.01% |

### Graph-only render loop

This benchmark excludes map copying, trail drawing, avatar drawing, and final frame composition. It draws only graph assets and dynamic graph markers into a transparent overlay.

```bash
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --graph-only --frames 450 --unprepared
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --graph-only --frames 900 --unprepared
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --graph-only --frames 1800 --unprepared
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --graph-only --frames 450
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --graph-only --frames 900
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --graph-only --frames 1800
```

| Frames | Legacy graph-only (s) | Prepared assets (s) | Prepared graph-only (s) | Loop change |
|---:|---:|---:|---:|---:|
| 450 | 0.636101 | 0.003545 | 0.353052 | -44.50% |
| 900 | 1.660019 | 0.003363 | 0.705296 | -57.51% |
| 1,800 | 4.676300 | 0.004040 | 1.409449 | -69.86% |

Asset preparation runs once per preview or video. Static panel, grid, line, and font assets are reused for every frame; dynamic cursor and marker work remains per-frame. Pixel parity tests cover first/last frames plus trail/avatar overlap in landscape and portrait.

## Correctness invariants

Every benchmark result must report:

- distance count equals route point count
- sample count equals requested sample count
- camera-state count equals sample count

The benchmark intentionally does not assert a runtime threshold. Hardware,
Python version, and system load vary; optimization acceptance should compare
scaling and preserve existing camera/render output tests.

## Next measurement

Before changing `dynamic_camera_states`, capture camera-state golden outputs for
short routes and edge windows. GitNexus impact shows this function directly
feeds both preview and final render paths; re-run impact analysis before editing
it.
