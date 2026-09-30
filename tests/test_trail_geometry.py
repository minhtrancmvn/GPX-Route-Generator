from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from io import BytesIO
from math import dist

from PIL import Image, ImageDraw
import pytest

from gpx_route_generator.models import OutputFormat, RenderOptions, RoutePoint
from gpx_route_generator.renderer import compose_frame, visible_trail_points, world_to_frame


BACKGROUND = (232, 237, 242, 255)


def _options(*, output_format: OutputFormat = OutputFormat.LANDSCAPE) -> RenderOptions:
    return RenderOptions(
        output_format=output_format,
        duration_seconds=5,
        fps=1,
        show_distance=False,
        show_progress_bar=False,
        show_speed=False,
        show_elevation=False,
    )


def _world_points_from_screen(
    screen_points: list[tuple[float, float]],
    options: RenderOptions,
) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    camera_center = (10_000.0, 20_000.0)
    world_points = [
        (
            camera_center[0] + (x - options.width / 2) / options.scale,
            camera_center[1] + (y - options.height / 2) / options.scale,
        )
        for x, y in screen_points
    ]
    return world_points, camera_center


def _route_points(count: int) -> list[RoutePoint]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        RoutePoint(37.0 + index * 0.0001, -122.0 - index * 0.0001, time=start + timedelta(seconds=index))
        for index in range(count)
    ]


def _map_bytes(options: RenderOptions) -> bytes:
    image = Image.new("RGBA", (options.width, options.height), BACKGROUND)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _reference_frame(
    screen_points: list[tuple[float, float]],
    options: RenderOptions,
) -> Image.Image:
    image = Image.new("RGBA", (options.width, options.height), BACKGROUND)
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).line(screen_points, fill=(255, 47, 47, 224), width=options.trail_width, joint="curve")
    return Image.alpha_composite(image, overlay).convert("RGB")


def test_visible_trail_preserves_first_latest_and_crossings() -> None:
    options = _options()
    screen_points = [
        (-60.0, 220.0),
        (100.0, 220.0),
        (options.width / 2, options.height / 2),
        (options.width + 60.0, 220.0),
        (options.width / 2, options.height / 2),
        (options.width - 100.0, options.height - 220.0),
    ]
    world_points, camera_center = _world_points_from_screen(screen_points, options)

    visible = visible_trail_points(world_points, camera_center, options)

    assert visible[0] == screen_points[0]
    assert visible[-1] == screen_points[-1]
    assert visible.count((options.width / 2, options.height / 2)) == 2


def test_trail_decimation_preserves_sharp_turns_and_loops() -> None:
    options = _options()
    screen_points = [
        (100.0, 100.0),
        (200.0, 100.2),
        (300.0, 100.0),
        (300.0, 300.0),
        (100.0, 300.0),
        (100.0, 100.0),
        (500.0, 100.0),
    ]
    world_points, camera_center = _world_points_from_screen(screen_points, options)

    visible = visible_trail_points(world_points, camera_center, options)

    assert (300.0, 100.0) in visible
    assert (300.0, 300.0) in visible
    assert (100.0, 300.0) in visible
    assert visible.count((100.0, 100.0)) == 2


def test_straight_segment_deviation_is_at_most_one_pixel() -> None:
    options = _options()
    screen_points = [(100.0 + index * 3.0, 200.0 + (index % 2) * 0.2) for index in range(300)]
    world_points, camera_center = _world_points_from_screen(screen_points, options)

    visible = visible_trail_points(world_points, camera_center, options)

    assert len(visible) < 12
    start, end = visible[0], visible[-1]
    segment_length = dist(start, end)
    assert segment_length > 0
    for point in screen_points:
        deviation = abs((end[0] - start[0]) * (start[1] - point[1]) - (start[0] - point[0]) * (end[1] - start[1])) / segment_length
        assert deviation <= 1.0


def test_trail_margin_prevents_viewport_edge_gaps() -> None:
    options = replace(_options(), trail_width=12)
    screen_points = [
        (-20.0, options.height / 2),
        (-4.0, options.height / 2),
        (options.width + 4.0, options.height / 2),
        (options.width + 20.0, options.height / 2),
    ]
    world_points, camera_center = _world_points_from_screen(screen_points, options)

    visible = visible_trail_points(world_points, camera_center, options)
    image = Image.new("RGBA", (options.width, options.height), BACKGROUND)
    ImageDraw.Draw(image).line(visible, fill=(255, 47, 47, 224), width=options.trail_width)

    assert image.getpixel((0, options.height // 2)) != BACKGROUND
    assert image.getpixel((options.width - 1, options.height // 2)) != BACKGROUND


def test_culling_preserves_an_offscreen_loop_that_crosses_viewport() -> None:
    options = _options()
    screen_points = [
        (-100.0, options.height / 2),
        (options.width + 100.0, options.height / 2),
        (options.width + 100.0, options.height + 100.0),
        (-100.0, options.height + 100.0),
        (-100.0, options.height / 2),
        (options.width + 100.0, options.height / 2),
    ]
    world_points, camera_center = _world_points_from_screen(screen_points, options)

    visible = visible_trail_points(world_points, camera_center, options)

    assert visible == screen_points


def test_portrait_and_landscape_trails_match_reference_pixels() -> None:
    for output_format in (OutputFormat.LANDSCAPE, OutputFormat.PORTRAIT):
        options = _options(output_format=output_format)
        screen_points = [
            (-40.0, options.height * 0.35),
            (options.width * 0.2, options.height * 0.35),
            (options.width * 0.5, options.height * 0.55),
            (options.width + 100.0, options.height * 0.55),
        ]
        world_points, camera_center = _world_points_from_screen(screen_points, options)
        actual = compose_frame(
            _map_bytes(options),
            _route_points(len(world_points)),
            world_points,
            [float(index) for index in range(len(world_points))],
            len(world_points) - 1,
            camera_center,
            options,
        ).convert("RGB")

        projected_points = [world_to_frame(point, camera_center, options) for point in world_points]
        assert actual.tobytes() == _reference_frame(projected_points, options).tobytes()


def test_long_nearly_straight_route_submits_few_points() -> None:
    options = _options()
    screen_points = [(50.0 + index, options.height / 2 + (index % 3) * 0.15) for index in range(1_800)]
    world_points, camera_center = _world_points_from_screen(screen_points, options)

    visible = visible_trail_points(world_points, camera_center, options)

    assert len(visible) < 16
    assert visible[0] == screen_points[0]
    assert visible[-1] == pytest.approx(screen_points[-1])


def test_world_to_frame_matches_visible_point_projection() -> None:
    options = _options()
    world_points, camera_center = _world_points_from_screen([(100.0, 300.0), (400.0, 300.0)], options)

    assert visible_trail_points(world_points, camera_center, options) == [
        world_to_frame(point, camera_center, options) for point in world_points
    ]
