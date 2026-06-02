from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO

from PIL import Image

from gpx_route_generator.geo import lat_lon_to_world_pixel
from gpx_route_generator.models import RenderOptions, RoutePoint
from gpx_route_generator.renderer import compose_frame, make_arrow


BACKGROUND = (232, 237, 242)


def make_map_bytes(options: RenderOptions) -> bytes:
    image = Image.new("RGB", (options.width, options.height), BACKGROUND)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_route() -> tuple[list[RoutePoint], list[tuple[float, float]], list[float]]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    samples = [
        RoutePoint(37.0000, -122.0000, elevation=10, time=start),
        RoutePoint(37.0004, -122.0004, elevation=26, time=start + timedelta(seconds=5)),
        RoutePoint(37.0007, -122.0007, elevation=18, time=start + timedelta(seconds=9)),
    ]
    pixels = [lat_lon_to_world_pixel(sample.lat, sample.lon, RenderOptions().zoom) for sample in samples]
    distances = [0.0, 60.0, 115.0]
    return samples, pixels, distances


def render_graph_frame(show_speed: bool, show_elevation: bool) -> Image.Image:
    options = RenderOptions(
        show_distance=False,
        show_progress_bar=False,
        show_speed=show_speed,
        show_elevation=show_elevation,
    )
    samples, sample_world_pixels, sample_distances = make_route()
    return compose_frame(
        map_bytes=make_map_bytes(options),
        samples=samples,
        sample_world_pixels=sample_world_pixels,
        sample_distances=sample_distances,
        frame_index=1,
        camera_center_world=sample_world_pixels[1],
        options=options,
    ).convert("RGB")


def test_avatar_size_scales_visible_sprite() -> None:
    small = make_arrow(24).getchannel("A").getbbox()
    large = make_arrow(96).getchannel("A").getbbox()

    assert small is not None
    assert large is not None
    small_long_axis = max(small[2] - small[0], small[3] - small[1])
    large_long_axis = max(large[2] - large[0], large[3] - large[1])
    assert large_long_axis > small_long_axis * 3

def test_default_avatar_renders_blob_icon() -> None:
    image = make_arrow(54, "default")
    assert image.size == (54, 54)
    assert image.getchannel("A").getbbox() is not None

def test_distance_badge_uses_fixed_top_left_hud_position() -> None:
    options = RenderOptions(
        show_distance=True,
        show_progress_bar=True,
        show_speed=False,
        show_elevation=False,
    )
    samples, sample_world_pixels, sample_distances = make_route()
    image = compose_frame(
        map_bytes=make_map_bytes(options),
        samples=samples,
        sample_world_pixels=sample_world_pixels,
        sample_distances=sample_distances,
        frame_index=2,
        camera_center_world=sample_world_pixels[2],
        options=options,
    ).convert("RGB")

    x = max(24, int(options.width * 0.05)) + 6
    y = max(28, int(options.width * 0.045)) + max(10, int(options.height * 0.014)) + 6
    assert image.getpixel((x, y)) != BACKGROUND

def test_speed_and_elevation_graphs_split_bottom_area() -> None:
    image = render_graph_frame(show_speed=True, show_elevation=True)
    y = image.height - 72

    assert image.getpixel((image.width // 4, y)) != BACKGROUND
    assert image.getpixel((image.width * 3 // 4, y)) != BACKGROUND
    assert image.getpixel((image.width // 2, y)) == BACKGROUND


def test_single_metric_graph_uses_full_width_bottom_area() -> None:
    image = render_graph_frame(show_speed=True, show_elevation=False)
    y = image.height - 72

    assert image.getpixel((image.width // 2, y)) != BACKGROUND


def test_no_metric_graph_leaves_bottom_area_clear() -> None:
    image = render_graph_frame(show_speed=False, show_elevation=False)
    y = image.height - 72

    assert image.getpixel((image.width // 2, y)) == BACKGROUND
