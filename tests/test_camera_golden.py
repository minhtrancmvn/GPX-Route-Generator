from __future__ import annotations

import pytest

from gpx_route_generator.geo import cumulative_distances, dynamic_camera_states
from gpx_route_generator.models import RoutePoint


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        (
            [
                RoutePoint(10.776, 106.700),
                RoutePoint(10.790, 106.730),
                RoutePoint(10.820, 106.760),
                RoutePoint(10.850, 106.810),
            ],
            [
                (14, (3340375.745422222, 1970818.3532337304)),
                (14, (3340567.984355556, 1970727.0292050538)),
                (14, (3340917.509688889, 1970413.8980598506)),
                (14, (3341447.6231111116, 1970058.036506477)),
            ],
        ),
        (
            [
                RoutePoint(37.000, -122.000),
                RoutePoint(37.000, -122.000),
                RoutePoint(37.005, -122.010),
                RoutePoint(37.010, -122.020),
            ],
            [
                (14, (675748.9777777779, 1632549.240124106)),
                (14, (675748.9777777779, 1632549.240124106)),
                (14, (675658.6837333334, 1632492.708068856)),
                (14, (675542.1752888889, 1632419.7597630913)),
            ],
        ),
        (
            [
                RoutePoint(0.0, 0.0),
                RoutePoint(0.0, 0.0001),
            ],
            [
                (14, (2097152.2621440003, 2097152.0)),
                (14, (2097152.9029404446, 2097152.0)),
            ],
        ),
        (
            [
                RoutePoint(51.5000, -0.1200),
                RoutePoint(51.5050, -0.1150),
                RoutePoint(51.5100, -0.1100),
                RoutePoint(51.5150, -0.1050),
            ],
            [
                (14, (2095767.0058666666, 1394830.5811929828)),
                (14, (2095799.0456888888, 1394779.109985667)),
                (14, (2095857.299911111, 1394685.518013573)),
                (14, (2095915.5541333333, 1394591.9157697707)),
            ],
        ),
    ],
    ids=("normal_route", "duplicate_distances", "short_route", "first_last_windows"),
)
def test_dynamic_camera_matches_baseline_goldens(
    points: list[RoutePoint],
    expected: list[tuple[int, tuple[float, float]]],
) -> None:
    """Catch changed camera zoom or center behavior for representative routes."""
    distances = cumulative_distances(points)
    states = dynamic_camera_states(
        points,
        distances,
        width=1280,
        height=720,
        scale=2,
        max_zoom=14,
        duration_seconds=10,
        fps=24,
    )
    assert len(states) == len(expected)
    for actual, (expected_zoom, expected_center) in zip(states, expected):
        assert actual.zoom == expected_zoom
        assert actual.center_world == pytest.approx(expected_center, abs=1e-9)
