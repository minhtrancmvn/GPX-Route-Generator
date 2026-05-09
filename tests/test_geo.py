from __future__ import annotations

import pytest

from gpx_route_generator.geo import (
    compute_bearing_degrees,
    cumulative_distances,
    dynamic_camera_states,
    fit_overview_zoom,
    lat_lon_to_world_pixel,
    local_route_window_points,
    overview_camera_world_pixels,
    project_to_frame,
    route_center_world_pixel,
    resample_by_distance,
    smooth_camera_world_pixels,
    world_pixel_to_lat_lon,
    dynamic_route_window_meters,
)
from gpx_route_generator.models import OutputFormat, RenderOptions, RoutePoint, validate_render_options


def test_world_pixel_projection_round_trips() -> None:
    lat, lon = 37.7749, -122.4194
    x, y = lat_lon_to_world_pixel(lat, lon, zoom=16)
    actual_lat, actual_lon = world_pixel_to_lat_lon(x, y, zoom=16)
    assert actual_lat == pytest.approx(lat)
    assert actual_lon == pytest.approx(lon)


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        (OutputFormat.LANDSCAPE, (640, 360)),
        (OutputFormat.PORTRAIT, (360, 640)),
    ],
)
def test_project_center_for_supported_formats(output_format: OutputFormat, expected: tuple[int, int]) -> None:
    options = RenderOptions(output_format=output_format)
    projected = project_to_frame(
        point_lat=10,
        point_lon=20,
        center_lat=10,
        center_lon=20,
        zoom=options.zoom,
        width=options.width,
        height=options.height,
        scale=options.scale,
    )
    assert projected == pytest.approx(expected)


def test_resample_by_distance_keeps_endpoints_and_count() -> None:
    points = [
        RoutePoint(37.0, -122.0, 10),
        RoutePoint(37.001, -122.0, 20),
        RoutePoint(37.002, -122.0, 30),
    ]
    samples, distances = resample_by_distance(points, 5)
    assert len(samples) == 5
    assert len(distances) == 5
    assert samples[0].lat == pytest.approx(points[0].lat)
    assert samples[-1].lat == pytest.approx(points[-1].lat)
    assert distances[0] == 0
    assert distances[-1] > 0


def test_bearing_points_east() -> None:
    bearing = compute_bearing_degrees(RoutePoint(0, 0), RoutePoint(0, 1))
    assert bearing == pytest.approx(90, abs=0.01)




def test_overview_zoom_fits_route_without_extra_zoom_out() -> None:
    points = [
        RoutePoint(37.0, -122.0),
        RoutePoint(37.01, -122.01),
        RoutePoint(37.02, -122.02),
    ]
    zoom = fit_overview_zoom(points, max_zoom=16, width=1280, height=720, scale=2)
    assert zoom >= 1
    assert zoom == fit_overview_zoom(
        points,
        max_zoom=16,
        width=1280,
        height=720,
        scale=2,
        context_zoom_out=0,
    )


def test_overview_zoom_prefers_tighter_fit_than_old_context_defaults() -> None:
    points = [
        RoutePoint(10.65, 106.60),
        RoutePoint(10.72, 106.76),
        RoutePoint(10.86, 106.92),
    ]
    close_zoom = fit_overview_zoom(points, max_zoom=16, width=1280, height=720, scale=2)
    loose_zoom = fit_overview_zoom(
        points,
        max_zoom=16,
        width=1280,
        height=720,
        scale=2,
        padding_ratio=0.30,
        context_zoom_out=1,
    )
    assert close_zoom > loose_zoom


def test_overview_camera_biases_toward_route_center() -> None:
    points = [RoutePoint(0, 0), RoutePoint(0, 0.01), RoutePoint(0, 0.02)]
    centers = overview_camera_world_pixels(points, zoom=15, smoothing=0.0, follow_ratio=0.18)
    route_center = route_center_world_pixel(points, zoom=15)
    first_point = lat_lon_to_world_pixel(points[0].lat, points[0].lon, zoom=15)
    assert abs(centers[0][0] - route_center[0]) < abs(first_point[0] - route_center[0])


def test_local_route_window_adds_neighbor_for_sparse_points() -> None:
    points = [RoutePoint(0, 0), RoutePoint(0, 1)]
    distances = cumulative_distances(points)
    window = local_route_window_points(points, distances, 0, window_meters=1)
    assert len(window) == 2


def test_dynamic_route_window_has_long_route_cap() -> None:
    # 500 km / 10 s → 125 000 m/s * 2.5 = 125 000 → capped at 50 000
    assert dynamic_route_window_meters(500_000, duration_seconds=10) == pytest.approx(50_000)
    # 2 000 km / 10 s → 500 000 → capped at 50 000
    assert dynamic_route_window_meters(2_000_000, duration_seconds=10) == pytest.approx(50_000)


def test_dynamic_route_window_short_trip_long_duration_zooms_in() -> None:
    # 5 km / 30 s → 417 m/s * 2.5 = 1 042 → clamped to min 1 000
    assert dynamic_route_window_meters(5_000, duration_seconds=30) == pytest.approx(1_000)
    # 20 km / 10 s → 2 000 * 2.5 = 5 000
    assert dynamic_route_window_meters(20_000, duration_seconds=10) == pytest.approx(5_000)


def test_dynamic_camera_zooms_closer_than_full_route_for_long_drive() -> None:
    coarse_points = [
        RoutePoint(10.776, 106.700),
        RoutePoint(10.930, 107.080),
        RoutePoint(11.280, 108.040),
        RoutePoint(12.240, 109.190),
        RoutePoint(13.750, 109.210),
    ]
    samples, distances = resample_by_distance(coarse_points, 120)
    full_route_zoom = fit_overview_zoom(samples, max_zoom=18, width=720, height=1280, scale=2)
    states = dynamic_camera_states(
        samples,
        distances,
        width=720,
        height=1280,
        scale=2,
        max_zoom=18,
        duration_seconds=10,
        fps=24,
    )
    assert full_route_zoom <= 7
    assert min(state.zoom for state in states) > full_route_zoom
    assert min(state.zoom for state in states) >= 9


def test_duration_validation_is_five_to_thirty_seconds() -> None:
    validate_render_options(RenderOptions(duration_seconds=5))
    validate_render_options(RenderOptions(duration_seconds=30))
    with pytest.raises(ValueError, match="Duration"):
        validate_render_options(RenderOptions(duration_seconds=4.9))
    with pytest.raises(ValueError, match="Duration"):
        validate_render_options(RenderOptions(duration_seconds=30.1))
