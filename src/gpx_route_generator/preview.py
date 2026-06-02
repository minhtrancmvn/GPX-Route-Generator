"""Single-frame preview rendering."""
from __future__ import annotations

from dataclasses import replace

from PIL import Image

from .geo import dynamic_camera_states, lat_lon_to_world_pixel, resample_by_distance, world_pixel_to_lat_lon
from .maps import GoogleStaticMapClient
from .models import RenderOptions, RoutePoint
from .renderer import compose_frame


def render_preview_frame_2d(
    points: list[RoutePoint],
    options: RenderOptions,
    map_client: GoogleStaticMapClient,
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
    camera_state = camera_states[0]
    center_x, center_y = camera_state.center_world
    center_lat, center_lon = world_pixel_to_lat_lon(center_x, center_y, camera_state.zoom)
    render_options = replace(options, zoom=camera_state.zoom)
    sample_world_pixels = [
        lat_lon_to_world_pixel(sample.lat, sample.lon, render_options.zoom)
        for sample in samples
    ]
    map_bytes = map_client.fetch(center_lat, center_lon, render_options)
    frame = compose_frame(
        map_bytes=map_bytes,
        samples=samples,
        sample_world_pixels=sample_world_pixels,
        sample_distances=sample_distances,
        frame_index=0,
        camera_center_world=(center_x, center_y),
        options=render_options,
    )
    return frame.convert("RGB")
