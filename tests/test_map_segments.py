from __future__ import annotations

from PIL import Image

from gpx_route_generator.geo import CameraState, lat_lon_to_world_pixel
from gpx_route_generator.map_segments import build_map_segment_plan, prepare_segment_frame
from gpx_route_generator.models import MAX_CACHED_MAP_REQUESTS, OutputFormat, RenderOptions


def camera_state(lat: float, lon: float, zoom: int = 14) -> CameraState:
    return CameraState(zoom=zoom, center_world=lat_lon_to_world_pixel(lat, lon, zoom))


def test_short_route_uses_one_source_image_at_target_zoom() -> None:
    options = RenderOptions()
    states = [
        camera_state(12.0, 108.0),
        camera_state(12.0005, 108.0005),
        camera_state(12.001, 108.001),
    ]

    plan = build_map_segment_plan(states, options)

    assert plan.map_request_count == 1
    assert plan.segments[0].source_zoom == options.zoom - 1
    assert [state.zoom for state in plan.camera_states] == [options.zoom] * len(states)
    assert plan.frame_segment_ids == (0, 0, 0)


def test_long_route_widens_camera_to_obey_segment_cap() -> None:
    options = RenderOptions()
    states = [camera_state(12.0, -130.0 + index * 1.34) for index in range(200)]

    plan = build_map_segment_plan(states, options)

    assert 1 < plan.map_request_count <= MAX_CACHED_MAP_REQUESTS
    assert min(state.zoom for state in plan.camera_states) < options.zoom
    assert len(plan.frame_segment_ids) == len(states)
    assert all(0 <= segment_id < plan.map_request_count for segment_id in plan.frame_segment_ids)


def test_portrait_route_uses_one_source_image() -> None:
    options = RenderOptions(output_format=OutputFormat.PORTRAIT)
    states = [camera_state(12.0, 108.0), camera_state(12.0005, 108.0005)]

    plan = build_map_segment_plan(states, options)

    assert plan.map_request_count == 1


def test_prepared_frame_uses_assigned_segment_and_output_dimensions() -> None:
    options = RenderOptions()
    states = [camera_state(12.0, 108.0), camera_state(12.0005, 108.0005)]
    plan = build_map_segment_plan(states, options)
    source = Image.new("RGBA", (1280, 1280), (16, 32, 48, 255))

    frame = prepare_segment_frame(source, plan.segment_for_frame(0), plan.camera_states[0], options)

    assert frame.size == (options.width, options.height)
    assert frame.getpixel((options.width // 2, options.height // 2)) == (16, 32, 48, 255)
