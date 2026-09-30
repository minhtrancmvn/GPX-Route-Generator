from __future__ import annotations

import argparse
import json
from io import BytesIO
from time import perf_counter

from PIL import Image, ImageDraw

from gpx_route_generator.geo import lat_lon_to_world_pixel
from gpx_route_generator.models import RenderOptions, RoutePoint
from gpx_route_generator.renderer import (
    compose_frame,
    draw_metric_graphs,
    draw_prepared_metric_graph_markers,
    prepare_metric_graphs,
)


def make_route(frame_count: int) -> list[RoutePoint]:
    """Build deterministic metric samples with timestamps and elevation values."""
    from datetime import UTC, datetime, timedelta

    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        RoutePoint(
            lat=37.0 + index * 0.0001,
            lon=-122.0 - index * 0.00008,
            elevation=10.0 + index % 100,
            time=start + timedelta(seconds=index),
        )
        for index in range(frame_count)
    ]


def benchmark_graph_only(
    *, frame_count: int, use_prepared_assets: bool = True
) -> dict[str, object]:
    """Measure graph drawing without map, trail, or avatar rendering."""
    options = RenderOptions(
        duration_seconds=1,
        fps=frame_count,
        show_distance=False,
        show_progress_bar=False,
        show_speed=True,
        show_elevation=True,
    )
    samples = make_route(frame_count)
    sample_distances = [float(index * 10) for index in range(frame_count)]
    preparation_started = perf_counter()
    prepared = (
        prepare_metric_graphs(samples, sample_distances, options)
        if use_prepared_assets
        else None
    )
    asset_preparation = perf_counter() - preparation_started
    if use_prepared_assets and prepared is None:
        raise RuntimeError("metric benchmark requires speed and elevation graphs")

    started = perf_counter()
    for frame_index in range(frame_count):
        overlay = Image.new("RGBA", (options.width, options.height), (0, 0, 0, 0))
        if prepared is None:
            draw_metric_graphs(
                ImageDraw.Draw(overlay),
                samples,
                sample_distances,
                frame_index,
                options,
            )
        else:
            overlay.paste(prepared.static_layer, mask=prepared.static_coverage)
            draw_prepared_metric_graph_markers(
                ImageDraw.Draw(overlay), prepared, frame_index
            )
    elapsed = perf_counter() - started
    return {
        "parameters": {"frame_count": frame_count},
        "timings_seconds": {
            "asset_preparation": asset_preparation,
            "graph_rendering": elapsed,
        },
        "correctness": {
            "graph_count": len(prepared.graphs) if prepared is not None else 2,
            "rendered_frame_count": frame_count,
        },
    }


def benchmark_metrics(
    *, frame_count: int, use_prepared_assets: bool = True
) -> dict[str, object]:
    """Measure whole-frame rendering, including map copy, trail, and avatar."""
    options = RenderOptions(
        duration_seconds=1,
        fps=frame_count,
        show_distance=False,
        show_progress_bar=False,
        show_speed=True,
        show_elevation=True,
    )
    samples = make_route(frame_count)
    sample_distances = [float(index * 10) for index in range(frame_count)]
    sample_world_pixels = [
        lat_lon_to_world_pixel(sample.lat, sample.lon, options.zoom)
        for sample in samples
    ]
    base_map = Image.new("RGBA", (options.width, options.height), (232, 237, 242, 255))
    preparation_started = perf_counter()
    prepared = (
        prepare_metric_graphs(samples, sample_distances, options)
        if use_prepared_assets
        else None
    )
    asset_preparation = perf_counter() - preparation_started
    if use_prepared_assets and prepared is None:
        raise RuntimeError("metric benchmark requires speed and elevation graphs")

    started = perf_counter()
    output_bytes = 0
    for frame_index in range(frame_count):
        frame = compose_frame(
            map_bytes=base_map,
            samples=samples,
            sample_world_pixels=sample_world_pixels,
            sample_distances=sample_distances,
            frame_index=frame_index,
            camera_center_world=sample_world_pixels[frame_index],
            options=options,
            **({"prepared_metric_graphs": prepared} if use_prepared_assets else {}),
        ).convert("RGB")
        if frame_index == frame_count - 1:
            buffer = BytesIO()
            frame.save(buffer, format="PNG")
            output_bytes = len(buffer.getvalue())
    elapsed = perf_counter() - started
    return {
        "parameters": {"frame_count": frame_count},
        "timings_seconds": {
            "asset_preparation": asset_preparation,
            "whole_frame_rendering": elapsed,
        },
        "correctness": {
            "graph_count": len(prepared.graphs) if prepared is not None else 2,
            "rendered_frame_count": frame_count,
        },
        "output_bytes": output_bytes,
    }


def main() -> None:
    """Run metric graph composition benchmark and emit JSON."""
    parser = argparse.ArgumentParser(
        description="Benchmark prepared metric graph composition."
    )
    parser.add_argument("--frames", type=int, default=900)
    parser.add_argument("--unprepared", action="store_true")
    parser.add_argument("--graph-only", action="store_true")
    args = parser.parse_args()
    benchmark = benchmark_graph_only if args.graph_only else benchmark_metrics
    print(
        json.dumps(
            benchmark(frame_count=args.frames, use_prepared_assets=not args.unprepared),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
