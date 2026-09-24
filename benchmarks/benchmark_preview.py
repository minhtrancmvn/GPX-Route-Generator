from __future__ import annotations

import argparse
from io import BytesIO
import json
from time import perf_counter

from gpx_route_generator.maps import SolidColorMapClient
from gpx_route_generator.models import RenderOptions
from gpx_route_generator.preview import render_preview_frame_2d

from .fixtures import make_route


def benchmark_preview(*, point_count: int, sample_count: int) -> dict[str, object]:
    points = make_route(point_count)
    options = RenderOptions(
        duration_seconds=1,
        fps=sample_count,
        show_speed=False,
        show_elevation=False,
    )
    map_client = SolidColorMapClient()
    started = perf_counter()
    image = render_preview_frame_2d(points, options, map_client)
    elapsed = perf_counter() - started
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return {
        "parameters": {
            "point_count": point_count,
            "sample_count": options.frame_count,
        },
        "timings_seconds": {"preview": elapsed},
        "correctness": {
            "map_requests": map_client.requests,
            "width": image.width,
            "height": image.height,
        },
        "output_bytes": len(buffer.getvalue()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark mocked-map preview rendering.")
    parser.add_argument("--point-count", type=int, default=900)
    parser.add_argument("--sample-count", type=int, default=900)
    args = parser.parse_args()
    print(
        json.dumps(
            benchmark_preview(
                point_count=args.point_count,
                sample_count=args.sample_count,
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
