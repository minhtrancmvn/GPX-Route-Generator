from __future__ import annotations

import argparse
import json
import platform
from datetime import datetime, timedelta, timezone
from time import perf_counter

from PIL import Image

from gpx_route_generator.models import RenderOptions, RoutePoint
from gpx_route_generator.renderer import compose_frame, visible_trail_points


def benchmark_trail(*, frames: int) -> dict[str, object]:
    """Measure one trail composition using a synthetic nearly straight route."""
    options = RenderOptions(
        duration_seconds=5,
        fps=max(1, frames // 5),
        show_distance=False,
        show_progress_bar=False,
        show_speed=False,
        show_elevation=False,
    )
    started_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    samples = [
        RoutePoint(37.0, -122.0, time=started_at + timedelta(seconds=index))
        for index in range(frames)
    ]
    center = (0.0, 0.0)
    world_points = [
        ((index - options.width / 2) / options.scale, (index % 3) * 0.075)
        for index in range(frames)
    ]
    visible_points = visible_trail_points(world_points, center, options)
    map_image = Image.new("RGBA", (options.width, options.height), (232, 237, 242, 255))
    started = perf_counter()
    frame = compose_frame(
        map_image,
        samples,
        world_points,
        [float(index) for index in range(frames)],
        frames - 1,
        center,
        options,
    )
    elapsed = perf_counter() - started
    frame.close()
    map_image.close()
    return {
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "parameters": {"frames": frames},
        "timings_seconds": {"compose_frame": elapsed},
        "correctness": {
            "submitted_point_count": len(visible_points),
            "source_point_count": len(world_points),
            "first_point_preserved": visible_points[0]
            == (0.0, options.height / 2),
            "latest_point_preserved": visible_points[-1]
            == (frames - 1.0, options.height / 2 + ((frames - 1) % 3) * 0.15),
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
