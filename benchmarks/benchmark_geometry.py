from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
from time import perf_counter
from typing import Callable, TypeVar

from gpx_route_generator.geo import (
    cumulative_distances,
    dynamic_camera_states,
    resample_by_distance,
)

from .fixtures import make_route

T = TypeVar("T")


def _measure(operation: Callable[[], T], repeats: int) -> tuple[float, T]:
    durations: list[float] = []
    result: T | None = None
    for _ in range(repeats):
        started = perf_counter()
        result = operation()
        durations.append(perf_counter() - started)
    assert result is not None
    return statistics.median(durations), result


def benchmark_geometry(
    *,
    point_count: int,
    sample_count: int,
    repeats: int = 3,
) -> dict[str, object]:
    points = make_route(point_count)
    distance_time, distances = _measure(lambda: cumulative_distances(points), repeats)
    resample_time, resampled = _measure(
        lambda: resample_by_distance(points, sample_count), repeats
    )
    samples, sample_distances = resampled
    camera_time, camera_states = _measure(
        lambda: dynamic_camera_states(
            samples,
            sample_distances,
            width=1280,
            height=720,
            scale=2,
            max_zoom=14,
            duration_seconds=30,
            fps=60,
        ),
        repeats,
    )
    return {
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "parameters": {
            "point_count": point_count,
            "sample_count": sample_count,
        },
        "timings_seconds": {
            "cumulative_distances": distance_time,
            "resample_by_distance": resample_time,
            "dynamic_camera_states": camera_time,
        },
        "correctness": {
            "distance_count": len(distances),
            "sample_count": len(samples),
            "camera_state_count": len(camera_states),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark GPX geometry stages.")
    parser.add_argument("--point-count", type=int, default=1_800)
    parser.add_argument("--sample-count", type=int, default=1_800)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    result = benchmark_geometry(
        point_count=args.point_count,
        sample_count=args.sample_count,
        repeats=args.repeats,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
