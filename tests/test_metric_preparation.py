from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image, ImageChops

from benchmarks.benchmark_metrics import benchmark_graph_only
from gpx_route_generator import renderer
from gpx_route_generator.geo import lat_lon_to_world_pixel
from gpx_route_generator.models import OutputFormat, RenderOptions, RoutePoint
from gpx_route_generator.renderer import (
    compose_frame,
    prepare_metric_graphs,
)

BACKGROUND = (232, 237, 242)
_OMITTED_PREPARED_ASSETS = object()


def make_options(
    *, output_format: OutputFormat = OutputFormat.LANDSCAPE
) -> RenderOptions:
    return RenderOptions(
        output_format=output_format,
        show_distance=False,
        show_progress_bar=False,
        show_speed=True,
        show_elevation=True,
    )


def make_map_bytes(options: RenderOptions) -> bytes:
    image = Image.new("RGB", (options.width, options.height), BACKGROUND)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_samples(
    *, timestamps: bool = True, elevations: bool = True
) -> list[RoutePoint]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    return [
        RoutePoint(
            37.0000,
            -122.0000,
            elevation=10.0 if elevations else None,
            time=start if timestamps else None,
        ),
        RoutePoint(
            37.0004,
            -122.0004,
            elevation=26.0 if elevations else None,
            time=start + timedelta(seconds=5) if timestamps else None,
        ),
        RoutePoint(
            37.0007,
            -122.0007,
            elevation=18.0 if elevations else None,
            time=start + timedelta(seconds=9) if timestamps else None,
        ),
    ]


def compose_graph_frame(
    options: RenderOptions,
    samples: list[RoutePoint],
    frame_index: int,
    *,
    prepared_metric_graphs: object = _OMITTED_PREPARED_ASSETS,
) -> Image.Image:
    sample_distances = [0.0, 60.0, 115.0]
    sample_world_pixels = [
        lat_lon_to_world_pixel(sample.lat, sample.lon, options.zoom)
        for sample in samples
    ]
    return compose_frame(
        map_bytes=make_map_bytes(options),
        samples=samples,
        sample_world_pixels=sample_world_pixels,
        sample_distances=sample_distances,
        frame_index=frame_index,
        camera_center_world=sample_world_pixels[frame_index],
        options=options,
        **(
            {}
            if prepared_metric_graphs is _OMITTED_PREPARED_ASSETS
            else {"prepared_metric_graphs": prepared_metric_graphs}
        ),
    ).convert("RGB")


def test_prepare_metrics_hides_speed_without_timestamps() -> None:
    options = make_options()
    prepared = prepare_metric_graphs(
        make_samples(timestamps=False), [0.0, 60.0, 115.0], options
    )

    assert prepared is not None
    assert [graph.label for graph in prepared.graphs] == ["Elevation"]


def test_prepare_metrics_hides_elevation_without_values() -> None:
    options = make_options()
    prepared = prepare_metric_graphs(
        make_samples(elevations=False), [0.0, 60.0, 115.0], options
    )

    assert prepared is not None
    assert [graph.label for graph in prepared.graphs] == ["Speed"]


def test_prepare_metrics_returns_none_when_no_series_available() -> None:
    options = make_options()

    prepared = prepare_metric_graphs(
        make_samples(timestamps=False, elevations=False),
        [0.0, 60.0, 115.0],
        options,
    )

    assert prepared is None


def test_prepare_metrics_preserves_unavailable_first_speed_value() -> None:
    options = make_options()

    prepared = prepare_metric_graphs(make_samples(), [0.0, 60.0, 115.0], options)

    assert prepared is not None
    speed = next(graph for graph in prepared.graphs if graph.label == "Speed")
    assert speed.points[0] is None


def test_prepare_metrics_handles_constant_and_gapped_series() -> None:
    options = make_options()
    start = datetime(2024, 1, 1, tzinfo=UTC)
    samples = [
        RoutePoint(37.0, -122.0, elevation=12.0, time=start),
        RoutePoint(37.1, -122.1, elevation=None, time=start + timedelta(seconds=5)),
        RoutePoint(37.2, -122.2, elevation=12.0, time=start + timedelta(seconds=10)),
    ]

    prepared = prepare_metric_graphs(samples, [0.0, 60.0, 120.0], options)

    assert prepared is not None
    elevation = next(graph for graph in prepared.graphs if graph.label == "Elevation")
    assert elevation.segments == (((elevation.points[0],), (elevation.points[2],)))
    assert elevation.minimum < elevation.maximum


def test_prepared_graph_marker_matches_first_and_last_frame() -> None:
    options = make_options()
    samples = make_samples()
    prepared = prepare_metric_graphs(samples, [0.0, 60.0, 115.0], options)

    assert prepared is not None
    for frame_index in (0, len(samples) - 1):
        prepared_frame = compose_graph_frame(
            options, samples, frame_index, prepared_metric_graphs=prepared
        )
        per_frame_frame = compose_graph_frame(options, samples, frame_index)

        assert ImageChops.difference(prepared_frame, per_frame_frame).getbbox() is None


def test_prepared_graphs_match_per_frame_rendering_in_landscape_and_portrait() -> None:
    samples = make_samples()
    for output_format in (OutputFormat.LANDSCAPE, OutputFormat.PORTRAIT):
        options = make_options(output_format=output_format)
        prepared = prepare_metric_graphs(samples, [0.0, 60.0, 115.0], options)

        assert prepared is not None
        prepared_frame = compose_graph_frame(
            options, samples, 1, prepared_metric_graphs=prepared
        )
        per_frame_frame = compose_graph_frame(options, samples, 1)

        assert ImageChops.difference(prepared_frame, per_frame_frame).getbbox() is None


def test_explicit_prepared_empty_assets_skip_per_frame_metric_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = make_options()
    samples = make_samples(timestamps=False, elevations=False)
    prepared = prepare_metric_graphs(samples, [0.0, 60.0, 115.0], options)

    assert prepared is None
    calls = {"graphs": 0, "speed": 0, "elevation": 0}

    def fail_graph_draw(*_args: object, **_kwargs: object) -> None:
        calls["graphs"] += 1
        raise AssertionError("metric graph drawing must not run")

    def fail_speed_series(*_args: object, **_kwargs: object) -> list[float | None]:
        calls["speed"] += 1
        raise AssertionError("speed series must not be re-evaluated")

    def fail_elevation_series(*_args: object, **_kwargs: object) -> list[float | None]:
        calls["elevation"] += 1
        raise AssertionError("elevation series must not be re-evaluated")

    monkeypatch.setattr(renderer, "draw_metric_graphs", fail_graph_draw)
    monkeypatch.setattr(renderer, "speed_series", fail_speed_series)
    monkeypatch.setattr(renderer, "elevation_series", fail_elevation_series)
    image = compose_graph_frame(options, samples, 1, prepared_metric_graphs=prepared)

    assert image.getpixel((image.width // 2, image.height - 72)) == BACKGROUND
    assert calls == {"graphs": 0, "speed": 0, "elevation": 0}


def test_omitted_prepared_assets_keep_legacy_metric_rendering() -> None:
    options = make_options()
    samples = make_samples()

    prepared = prepare_metric_graphs(samples, [0.0, 60.0, 115.0], options)

    assert prepared is not None
    legacy_frame = compose_graph_frame(options, samples, 1)
    prepared_frame = compose_graph_frame(
        options, samples, 1, prepared_metric_graphs=prepared
    )

    assert ImageChops.difference(legacy_frame, prepared_frame).getbbox() is None


def test_graph_only_benchmark_reports_preparation_and_rendering_timings() -> None:
    result = benchmark_graph_only(frame_count=3, use_prepared_assets=True)

    assert result["parameters"] == {"frame_count": 3}
    assert result["correctness"] == {"graph_count": 2, "rendered_frame_count": 3}
    assert set(result["timings_seconds"]) == {"asset_preparation", "graph_rendering"}


@pytest.mark.parametrize(
    "output_format", [OutputFormat.LANDSCAPE, OutputFormat.PORTRAIT]
)
def test_prepared_graphs_replace_overlapping_trail_and_avatar_pixels(
    output_format: OutputFormat,
) -> None:
    options = replace(make_options(output_format=output_format), arrow_size=180)
    samples = make_samples()
    sample_distances = [0.0, 60.0, 115.0]
    prepared = prepare_metric_graphs(samples, sample_distances, options)

    assert prepared is not None
    graph_center = (
        (prepared.graphs[0].bounds[0] + prepared.graphs[0].bounds[2]) / 2,
        (prepared.graphs[0].bounds[1] + prepared.graphs[0].bounds[3]) / 2,
    )
    camera_center_world = (0.0, 0.0)
    graph_world_pixel = (
        graph_center[0] - options.width / 2,
        graph_center[1] - options.height / 2,
    )
    sample_world_pixels = [graph_world_pixel, graph_world_pixel, graph_world_pixel]
    map_bytes = make_map_bytes(options)
    legacy_frame = compose_frame(
        map_bytes=map_bytes,
        samples=samples,
        sample_world_pixels=sample_world_pixels,
        sample_distances=sample_distances,
        frame_index=2,
        camera_center_world=camera_center_world,
        options=options,
    ).convert("RGB")
    prepared_frame = compose_frame(
        map_bytes=map_bytes,
        samples=samples,
        sample_world_pixels=sample_world_pixels,
        sample_distances=sample_distances,
        frame_index=2,
        camera_center_world=camera_center_world,
        options=options,
        prepared_metric_graphs=prepared,
    ).convert("RGB")

    assert ImageChops.difference(legacy_frame, prepared_frame).getbbox() is None
