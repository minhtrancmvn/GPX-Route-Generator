from __future__ import annotations

import json

from benchmarks.benchmark_geometry import benchmark_geometry
from benchmarks.benchmark_preview import benchmark_preview
from benchmarks.fixtures import make_route


def test_make_route_is_deterministic_and_reaches_requested_point_count() -> None:
    first = make_route(12)
    second = make_route(12)

    assert first == second
    assert len(first) == 12
    assert first[0].lat == 37.0
    assert first[-1].lon < first[0].lon


def test_geometry_benchmark_reports_all_stages_and_environment() -> None:
    result = benchmark_geometry(point_count=24, sample_count=12)

    assert result["parameters"] == {"point_count": 24, "sample_count": 12}
    assert set(result["timings_seconds"]) == {
        "cumulative_distances",
        "resample_by_distance",
        "dynamic_camera_states",
    }
    assert all(value >= 0 for value in result["timings_seconds"].values())
    assert result["correctness"] == {
        "distance_count": 24,
        "sample_count": 12,
        "camera_state_count": 12,
    }
    assert result["environment"]["python"]


def test_geometry_benchmark_json_is_serializable() -> None:
    payload = benchmark_geometry(point_count=8, sample_count=4)

    encoded = json.dumps(payload, sort_keys=True)

    assert '"camera_state_count": 4' in encoded


def test_preview_benchmark_reports_map_requests_and_output_size() -> None:
    result = benchmark_preview(point_count=12, sample_count=8)

    assert result["parameters"] == {"point_count": 12, "sample_count": 8}
    assert result["correctness"]["map_requests"] == 1
    assert result["correctness"]["width"] == 1280
    assert result["correctness"]["height"] == 720
    assert result["timings_seconds"]["preview"] >= 0
    assert result["output_bytes"] > 0
