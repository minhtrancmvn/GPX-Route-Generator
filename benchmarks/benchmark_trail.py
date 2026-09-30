from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timedelta, timezone
from time import perf_counter
from unittest.mock import patch

from PIL import Image, ImageDraw

import gpx_route_generator.renderer as renderer
from gpx_route_generator.models import RenderOptions, RoutePoint
from gpx_route_generator.renderer import compose_frame, visible_trail_points, world_to_frame


def _options(frames: int) -> RenderOptions:
    return RenderOptions(
        duration_seconds=5,
        fps=max(1, frames // 5),
        show_distance=False,
        show_progress_bar=False,
        show_speed=False,
        show_elevation=False,
    )


def _fixture_world_points(frames: int, fixture: str, options: RenderOptions) -> list[tuple[float, float]]:
    if fixture == "straight":
        return [
            ((index - options.width / 2) / options.scale, (index % 3) * 0.075)
            for index in range(frames)
        ]
    if fixture == "zigzag":
        return [
            (
                (index - options.width / 2) / options.scale,
                ((index % 2) * 8.0 - 4.0) / options.scale,
            )
            for index in range(frames)
        ]
    if fixture == "moving_zigzag":
        return [
            (index * 2.0, ((index % 2) * 80.0 - 40.0) / options.scale)
            for index in range(frames)
        ]
    raise ValueError(f"Unknown fixture: {fixture}")


def _legacy_trail_points(
    sample_world_pixels: list[tuple[float, float]],
    camera_center_world: tuple[float, float],
    options: RenderOptions,
) -> list[tuple[float, float]]:
    return [world_to_frame(point, camera_center_world, options) for point in sample_world_pixels]


def _measure_whole_render(
    *,
    frames: int,
    fixture: str,
    optimized: bool,
) -> tuple[float, int, list[tuple[float, float]]]:
    options = _options(frames)
    started_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    samples = [
        RoutePoint(37.0, -122.0, time=started_at + timedelta(seconds=index))
        for index in range(frames)
    ]
    world_points = _fixture_world_points(frames, fixture, options)
    distances = [float(index) for index in range(frames)]
    map_image = Image.new("RGBA", (options.width, options.height), (232, 237, 242, 255))
    submitted_points = 0
    final_points: list[tuple[float, float]] = []
    point_builder = visible_trail_points if optimized else _legacy_trail_points

    def measured_draw_trail(
        draw: ImageDraw.ImageDraw,
        sample_world_pixels: list[tuple[float, float]],
        frame_index: int,
        camera_center_world: tuple[float, float],
        render_options: RenderOptions,
    ) -> None:
        nonlocal final_points, submitted_points
        if frame_index <= 0:
            return
        points = point_builder(
            sample_world_pixels[: frame_index + 1], camera_center_world, render_options
        )
        submitted_points += len(points)
        if frame_index == frames - 1:
            final_points = points
        draw.line(points, fill=(255, 47, 47, 224), width=render_options.trail_width, joint="curve")

    started = perf_counter()
    with patch.object(renderer, "draw_trail", new=measured_draw_trail):
        for frame_index in range(frames):
            frame = compose_frame(
                map_image,
                samples,
                world_points,
                distances,
                frame_index,
                world_points[frame_index],
                options,
            )
            frame.close()
    elapsed = perf_counter() - started
    map_image.close()
    return elapsed, submitted_points, final_points


def benchmark_trail(*, frames: int) -> dict[str, object]:
    """Compare legacy and optimized complete trail rendering for two fixtures."""
    fixtures: dict[str, dict[str, float | int]] = {}
    for fixture in ("straight", "zigzag", "moving_zigzag"):
        legacy_seconds, legacy_submitted_points, _ = _measure_whole_render(
            frames=frames,
            fixture=fixture,
            optimized=False,
        )
        optimized_seconds, optimized_submitted_points, optimized_final_points = _measure_whole_render(
            frames=frames,
            fixture=fixture,
            optimized=True,
        )
        options = _options(frames)
        world_points = _fixture_world_points(frames, fixture, options)
        camera_center = world_points[-1]
        expected_first = world_to_frame(world_points[0], camera_center, options)
        expected_latest = world_to_frame(world_points[-1], camera_center, options)
        fixtures[fixture] = {
            "legacy_seconds": legacy_seconds,
            "optimized_seconds": optimized_seconds,
            "legacy_submitted_points": legacy_submitted_points,
            "optimized_submitted_points": optimized_submitted_points,
            "first_point_preserved": expected_first in optimized_final_points,
            "latest_point_preserved": expected_latest in optimized_final_points,
        }
    return {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "parameters": {"frames": frames},
        "fixtures": fixtures,
        "timings_seconds": {"compose_frame": fixtures["straight"]["optimized_seconds"]},
        "correctness": {
            "submitted_point_count": fixtures["straight"]["optimized_submitted_points"],
            "source_point_count": frames,
            "first_point_preserved": fixtures["straight"]["first_point_preserved"],
            "latest_point_preserved": fixtures["straight"]["latest_point_preserved"],
        },
    }


def main() -> None:
    """Print one JSON trail benchmark result."""
    parser = argparse.ArgumentParser(description="Benchmark trail geometry culling and decimation.")
    parser.add_argument("--frames", type=int, default=900)
    args = parser.parse_args()
    print(json.dumps(benchmark_trail(frames=args.frames), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
