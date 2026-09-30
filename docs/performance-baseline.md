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

Measured on 2026-09-30, macOS 27.0 arm64, Python 3.14.6. The deterministic benchmark renders every frame over an in-memory RGBA map with speed and elevation enabled. `--unprepared` is the old per-frame graph path; default uses `PreparedMetricGraphs`.

```bash
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 450 --unprepared
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 900 --unprepared
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 1800 --unprepared
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 450
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 900
PYTHONPATH=src python3 -m benchmarks.benchmark_metrics --frames 1800
```

| Frames | Before graph composition (s) | After preparation (s) | After graph composition (s) | Composition change |
|---:|---:|---:|---:|---:|
| 450 | 1.476537 | 0.002320 | 1.141262 | -22.71% |
| 900 | 3.737200 | 0.002624 | 2.898358 | -22.45% |
| 1,800 | 11.150574 | 0.003409 | 7.813747 | -29.03% |

Both modes rendered two graphs and requested frame counts. Asset preparation is reported separately because it runs once per preview/video, then frame composition reuses static panel, grid, line, and font assets. PNG byte totals differ because prepared static layers composite before dynamic cursor/marker state; pixel parity is covered for first, last, landscape, and portrait graph frames.

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
