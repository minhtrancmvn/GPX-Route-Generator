"""Single-frame preview rendering."""
from __future__ import annotations

from dataclasses import replace
from io import BytesIO

from PIL import Image

from .geo import dynamic_camera_states, lat_lon_to_world_pixel, resample_by_distance
from .map_segments import build_map_segment_plan, prepare_segment_frame
from .maps import StaticMapClient
from .models import RenderOptions, RoutePoint
from .renderer import compose_frame


def render_preview_frame_2d(
    points: list[RoutePoint],
    options: RenderOptions,
    map_client: StaticMapClient,
) -> Image.Image:
    samples, sample_distances = resample_by_distance(points, options.frame_count)
    camera_states = dynamic_camera_states(
        samples,
        sample_distances,
        width=options.width,
        height=options.height,
        scale=options.scale,
        max_zoom=options.zoom,
        duration_seconds=options.duration_seconds,
        fps=options.fps,
    )
    plan = build_map_segment_plan(camera_states, options)
    camera_state = plan.camera_states[0]
    render_options = replace(options, zoom=camera_state.zoom)
    sample_world_pixels = [
        lat_lon_to_world_pixel(sample.lat, sample.lon, render_options.zoom)
        for sample in samples
    ]
    segment = plan.segment_for_frame(0)
    center_lat, center_lon = segment.center_lat_lon
    map_bytes = map_client.fetch(
        center_lat,
        center_lon,
        render_options,
        zoom=segment.source_zoom,
        static_size=(640, 640),
    )
    source_image = Image.open(BytesIO(map_bytes)).convert("RGBA")
    try:
        prepared_map = prepare_segment_frame(source_image, segment, camera_state, render_options)
        frame = compose_frame(
            map_bytes=prepared_map,
            samples=samples,
            sample_world_pixels=sample_world_pixels,
            sample_distances=sample_distances,
            frame_index=0,
            camera_center_world=camera_state.center_world,
            options=render_options,
        )
        return frame.convert("RGB")
    finally:
        source_image.close()
