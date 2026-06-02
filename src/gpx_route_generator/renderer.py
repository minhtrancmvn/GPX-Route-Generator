from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import os
import subprocess

from PIL import Image, ImageDraw, ImageFont

from .geo import (
    compute_bearing_degrees,
    dynamic_camera_states,
    lat_lon_to_world_pixel,
    resample_by_distance,
    world_pixel_to_lat_lon,
)
from .maps import GoogleStaticMapClient
from .models import RenderOptions, RoutePoint, validate_render_options

ProgressCallback = Callable[[int, int, int], None]

_AVATAR_CACHE: dict[tuple[str, int], Image.Image] = {}


def _frame_worker_count() -> int:
    raw_value = os.getenv("FRAME_WORKERS")
    if raw_value:
        try:
            return max(1, min(12, int(raw_value)))
        except ValueError:
            return 4
    return 4


def _render_video_frame(
    *,
    index: int,
    samples: list[RoutePoint],
    sample_distances: list[float],
    camera_states,
    options: RenderOptions,
    map_client: GoogleStaticMapClient,
) -> bytes:
    camera_state = camera_states[index]
    render_options = replace(options, zoom=camera_state.zoom)
    center_x, center_y = camera_state.center_world
    sample_world_pixels = [
        lat_lon_to_world_pixel(sample.lat, sample.lon, render_options.zoom)
        for sample in samples
    ]
    center_lat, center_lon = world_pixel_to_lat_lon(center_x, center_y, render_options.zoom)
    map_bytes = map_client.fetch(center_lat, center_lon, render_options)
    frame = compose_frame(
        map_bytes=map_bytes,
        samples=samples,
        sample_world_pixels=sample_world_pixels,
        sample_distances=sample_distances,
        frame_index=index,
        camera_center_world=(center_x, center_y),
        options=render_options,
    )
    return frame.convert("RGB").tobytes()


def render_route_video(
    points: list[RoutePoint],
    options: RenderOptions,
    output_path: Path,
    map_client: GoogleStaticMapClient,
    ffmpeg_path: str = "ffmpeg",
    progress_callback: ProgressCallback | None = None,
) -> None:
    validate_render_options(options)
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
    output_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        ffmpeg_path,
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{options.width}x{options.height}",
        "-r",
        str(options.fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    map_requests = 0
    try:
        assert process.stdin is not None
        worker_count = min(_frame_worker_count(), options.frame_count)
        next_submit = 0
        next_write = 0
        pending: dict[int, Future[bytes]] = {}

        def submit_frame(executor: ThreadPoolExecutor, index: int) -> None:
            pending[index] = executor.submit(
                _render_video_frame,
                index=index,
                samples=samples,
                sample_distances=sample_distances,
                camera_states=camera_states,
                options=options,
                map_client=map_client,
            )

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            while next_submit < min(worker_count, options.frame_count):
                submit_frame(executor, next_submit)
                next_submit += 1

            while next_write < options.frame_count:
                future = pending.get(next_write)
                if future is not None and future.done():
                    frame_bytes = future.result()
                    del pending[next_write]
                    process.stdin.write(frame_bytes)
                    map_requests += 1
                    next_write += 1
                    if progress_callback:
                        progress_callback(next_write, options.frame_count, map_requests)
                    while next_submit < options.frame_count and len(pending) < worker_count:
                        submit_frame(executor, next_submit)
                        next_submit += 1
                    continue

                if pending:
                    wait(tuple(pending.values()), return_when=FIRST_COMPLETED)
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"ffmpeg failed with exit code {return_code}: {stderr[-1200:]}")
    except Exception:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        process.kill()
        process.wait()
        raise


def compose_frame(
    map_bytes: bytes,
    samples: list[RoutePoint],
    sample_world_pixels: list[tuple[float, float]],
    sample_distances: list[float],
    frame_index: int,
    camera_center_world: tuple[float, float],
    options: RenderOptions,
) -> Image.Image:
    frame = Image.open(BytesIO(map_bytes)).convert("RGBA")
    if frame.size != (options.width, options.height):
        frame = frame.resize((options.width, options.height), Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw_trail(draw, sample_world_pixels, frame_index, camera_center_world, options)
    if options.show_distance:
        draw_distance_badge(draw, sample_distances, frame_index, options)
    draw_arrow(overlay, samples, sample_world_pixels, frame_index, camera_center_world, options)
    if options.show_progress_bar:
        draw_progress_bar(draw, frame_index, options)
    draw_metric_graphs(draw, samples, sample_distances, frame_index, options)
    return Image.alpha_composite(frame, overlay)


def draw_trail(
    draw: ImageDraw.ImageDraw,
    sample_world_pixels: list[tuple[float, float]],
    frame_index: int,
    camera_center_world: tuple[float, float],
    options: RenderOptions,
) -> None:
    if frame_index <= 0:
        return
    color = parse_hex_color(options.trail_color, alpha=224)
    points = [
        world_to_frame(point, camera_center_world, options)
        for point in sample_world_pixels[: frame_index + 1]
    ]
    draw.line(points, fill=color, width=options.trail_width, joint="curve")


def draw_arrow(
    overlay: Image.Image,
    samples: list[RoutePoint],
    sample_world_pixels: list[tuple[float, float]],
    frame_index: int,
    camera_center_world: tuple[float, float],
    options: RenderOptions,
) -> None:
    if frame_index == 0:
        bearing = compute_bearing_degrees(samples[0], samples[min(1, len(samples) - 1)])
    else:
        bearing = compute_bearing_degrees(samples[frame_index - 1], samples[frame_index])
    arrow = make_arrow(options.arrow_size, options.avatar_id).rotate(-bearing, expand=True, resample=Image.Resampling.BICUBIC)
    arrow_x, arrow_y = world_to_frame(sample_world_pixels[frame_index], camera_center_world, options)
    x = int(arrow_x - arrow.width / 2)
    y = int(arrow_y - arrow.height / 2)
    overlay.alpha_composite(arrow, (x, y))


def make_arrow(size: int, avatar_id: str = "mt15") -> Image.Image:
    if avatar_id == "default":
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        shadow_offset = max(1, size // 18)
        inset = max(2, size // 12)
        draw.ellipse(
            (inset + shadow_offset, inset + shadow_offset, size - inset + shadow_offset, size - inset + shadow_offset),
            fill=(0, 0, 0, 85),
        )
        draw.ellipse(
            (inset, inset, size - inset, size - inset),
            fill=(0, 96, 240, 245),
            outline=(255, 255, 255, 235),
            width=max(2, size // 16),
        )
        highlight = max(3, size // 5)
        draw.ellipse(
            (size * 0.32, size * 0.28, size * 0.32 + highlight, size * 0.28 + highlight),
            fill=(255, 255, 255, 85),
        )
        return image

    avatar_path = Path(__file__).parent / f"{avatar_id}.png"
    if avatar_path.exists():
        cache_key = (avatar_id, size)
        if cache_key not in _AVATAR_CACHE:
            src = Image.open(avatar_path).convert("RGBA")
            content_box = src.getchannel("A").getbbox()
            if content_box is not None:
                src = src.crop(content_box)
            # Scale so the long axis (image width = front-to-back) matches size
            aspect = src.width / src.height
            new_w = size
            new_h = max(1, int(size / aspect))
            scaled = src.resize((new_w, new_h), Image.Resampling.LANCZOS)
            # Motorcycle faces right in image; rotate 90° CCW so it points up (north)
            upright = scaled.rotate(90, expand=True, resample=Image.Resampling.BICUBIC)
            _AVATAR_CACHE[cache_key] = upright
        return _AVATAR_CACHE[cache_key].copy()

    # Fallback: drawn polygon arrow
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    center = size / 2
    shaft_width = max(5, int(size * 0.18))
    points = [
        (center, size * 0.08),
        (size * 0.82, size * 0.56),
        (center + shaft_width, size * 0.50),
        (center + shaft_width, size * 0.90),
        (center - shaft_width, size * 0.90),
        (center - shaft_width, size * 0.50),
        (size * 0.18, size * 0.56),
    ]
    shadow = [(x + 2, y + 3) for x, y in points]
    draw.polygon(shadow, fill=(0, 0, 0, 92))
    draw.polygon(points, fill=(0, 104, 255, 245))
    draw.line(points + [points[0]], fill=(255, 255, 255, 230), width=max(2, size // 18), joint="curve")
    return image


def draw_distance_badge(
    draw: ImageDraw.ImageDraw,
    sample_distances: list[float],
    frame_index: int,
    options: RenderOptions,
) -> None:
    text = format_distance(sample_distances[frame_index])
    font = load_font(max(20, int(options.width * 0.032)), bold=True)
    pad_x = max(12, int(options.width * 0.018))
    pad_y = max(7, int(options.width * 0.010))
    bbox = draw.textbbox((0, 0), text, font=font)
    box_w = bbox[2] - bbox[0] + pad_x * 2
    box_h = bbox[3] - bbox[1] + pad_y * 2
    margin = max(24, int(options.width * 0.05))
    progress_bottom = max(28, int(options.width * 0.045))
    gap = max(10, int(options.height * 0.014))
    x = margin
    y = progress_bottom + gap if options.show_progress_bar else max(24, int(options.height * 0.035))
    radius = max(8, int(box_h * 0.35))
    draw.rounded_rectangle((x + 3, y + 4, x + box_w + 3, y + box_h + 4), radius=radius, fill=(0, 0, 0, 105))
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=radius, fill=(242, 26, 26, 245))
    draw.text((x + pad_x, y + pad_y - 1), text, fill=(255, 255, 255, 255), font=font)


def draw_metric_graphs(
    draw: ImageDraw.ImageDraw,
    samples: list[RoutePoint],
    sample_distances: list[float],
    frame_index: int,
    options: RenderOptions,
) -> None:
    metrics: list[tuple[str, list[float | None], tuple[int, int, int, int]]] = []
    if options.show_speed:
        metrics.append(("Speed", speed_series(samples, sample_distances), (63, 146, 255, 245)))
    if options.show_elevation:
        metrics.append(("Elevation", elevation_series(samples), (43, 204, 143, 245)))
    if not metrics:
        return

    margin_x = max(18, int(options.width * 0.035))
    margin_bottom = max(18, int(options.height * 0.030))
    gap = max(10, int(options.width * 0.014))
    graph_h = min(max(84, int(options.height * 0.15)), 150)
    x1 = margin_x
    x2 = options.width - margin_x
    y2 = options.height - margin_bottom
    y1 = y2 - graph_h

    if len(metrics) == 1:
        bounds = [(x1, y1, x2, y2)]
    else:
        mid_x = (x1 + x2) / 2
        bounds = [(x1, y1, mid_x - gap / 2, y2), (mid_x + gap / 2, y1, x2, y2)]

    for metric, metric_bounds in zip(metrics, bounds, strict=True):
        label, values, color = metric
        draw_metric_graph(draw, metric_bounds, label, values, frame_index, color, options)


def draw_metric_graph(
    draw: ImageDraw.ImageDraw,
    bounds: tuple[float, float, float, float],
    label: str,
    values: list[float | None],
    frame_index: int,
    color: tuple[int, int, int, int],
    options: RenderOptions,
) -> None:
    x1, y1, x2, y2 = bounds
    panel_w = x2 - x1
    panel_h = y2 - y1
    radius = max(8, int(panel_h * 0.12))
    draw.rounded_rectangle((x1 + 3, y1 + 4, x2 + 3, y2 + 4), radius=radius, fill=(0, 0, 0, 88))
    draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=(8, 16, 28, 212))

    font = load_font(max(13, min(20, int(options.width * 0.016))), bold=True)
    pad_x = max(12, int(panel_w * 0.035))
    pad_top = max(10, int(panel_h * 0.11))
    pad_bottom = max(10, int(panel_h * 0.12))
    label_bbox = draw.textbbox((0, 0), label, font=font)
    label_h = label_bbox[3] - label_bbox[1]
    draw.text((x1 + pad_x, y1 + pad_top), label, fill=(255, 255, 255, 235), font=font)

    chart_left = x1 + pad_x
    chart_right = x2 - pad_x
    chart_top = y1 + pad_top + label_h + max(8, int(panel_h * 0.08))
    chart_bottom = y2 - pad_bottom
    if chart_right <= chart_left or chart_bottom <= chart_top:
        return

    for ratio in (0.25, 0.5, 0.75):
        y = chart_top + (chart_bottom - chart_top) * ratio
        draw.line((chart_left, y, chart_right, y), fill=(255, 255, 255, 30), width=1)

    progress = 0.0 if len(values) <= 1 else frame_index / (len(values) - 1)
    cursor_x = chart_left + (chart_right - chart_left) * clamp(progress, 0.0, 1.0)
    draw.line((cursor_x, chart_top, cursor_x, chart_bottom), fill=(255, 255, 255, 70), width=1)

    valid_values = [value for value in values if value is not None]
    if not valid_values:
        y = chart_bottom
        draw.line((chart_left, y, chart_right, y), fill=(color[0], color[1], color[2], 120), width=2)
        return

    minimum = min(valid_values)
    maximum = max(valid_values)
    if minimum == maximum:
        padding = max(1.0, abs(maximum) * 0.1)
        minimum -= padding
        maximum += padding
    span = maximum - minimum

    def graph_point(index: int, value: float) -> tuple[float, float]:
        value_progress = (value - minimum) / span
        x = chart_left if len(values) <= 1 else chart_left + (chart_right - chart_left) * index / (len(values) - 1)
        y = chart_bottom - (chart_bottom - chart_top) * value_progress
        return x, y

    segment: list[tuple[float, float]] = []
    current_point: tuple[float, float] | None = None
    for index, value in enumerate(values):
        if value is None:
            if len(segment) > 1:
                draw.line(segment, fill=color, width=3, joint="curve")
            elif len(segment) == 1:
                x, y = segment[0]
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
            segment = []
            continue
        point = graph_point(index, value)
        if index == frame_index:
            current_point = point
        segment.append(point)
    if len(segment) > 1:
        draw.line(segment, fill=color, width=3, joint="curve")
    elif len(segment) == 1:
        x, y = segment[0]
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)

    if current_point is not None:
        x, y = current_point
        marker_r = max(4, int(panel_h * 0.045))
        draw.ellipse((x - marker_r, y - marker_r, x + marker_r, y + marker_r), fill=color, outline=(255, 255, 255, 235), width=2)


def draw_progress_bar(draw: ImageDraw.ImageDraw, frame_index: int, options: RenderOptions) -> None:
    margin = max(24, int(options.width * 0.05))
    bar_h = max(10, int(options.height * 0.010))
    x1 = margin
    x2 = options.width - margin
    y2 = max(28, int(options.width * 0.045))
    y1 = y2 - bar_h
    progress = 1.0 if options.frame_count <= 1 else frame_index / (options.frame_count - 1)
    draw.rounded_rectangle((x1, y1, x2, y2), radius=bar_h // 2, fill=(8, 16, 28, 170))
    draw.rounded_rectangle((x1, y1, x1 + (x2 - x1) * progress, y2), radius=bar_h // 2, fill=(246, 30, 30, 245))


def world_to_frame(
    world_pixel: tuple[float, float],
    camera_center_world: tuple[float, float],
    options: RenderOptions,
) -> tuple[float, float]:
    return (
        (world_pixel[0] - camera_center_world[0]) * options.scale + options.width / 2,
        (world_pixel[1] - camera_center_world[1]) * options.scale + options.height / 2,
    )


def parse_hex_color(value: str, alpha: int) -> tuple[int, int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        return (255, 47, 47, alpha)
    try:
        return (
            int(cleaned[0:2], 16),
            int(cleaned[2:4], 16),
            int(cleaned[4:6], 16),
            alpha,
        )
    except ValueError:
        return (255, 47, 47, alpha)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Helvetica.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def format_distance(distance_meters: float) -> str:
    km = max(0.0, distance_meters / 1000)
    if km >= 100:
        return f"{km:.0f} km"
    if km >= 10:
        return f"{km:.1f} km"
    return f"{km:.2f} km"


def format_elevation(elevation: float | None) -> str:
    if elevation is None:
        return "-- m"
    return f"{elevation:.0f} m"


def format_speed(samples: list[RoutePoint], sample_distances: list[float], frame_index: int) -> str:
    if frame_index <= 0:
        return "-- km/h"
    current = samples[frame_index]
    previous = samples[frame_index - 1]
    if current.time is None or previous.time is None:
        return "-- km/h"
    seconds = (current.time - previous.time).total_seconds()
    if seconds <= 0:
        return "-- km/h"
    meters = sample_distances[frame_index] - sample_distances[frame_index - 1]
    return f"{meters / seconds * 3.6:.0f} km/h"


def speed_series(samples: list[RoutePoint], sample_distances: list[float]) -> list[float | None]:
    values = [speed_at_frame(samples, sample_distances, frame_index) for frame_index in range(len(samples))]
    if len(values) > 1 and values[0] is None:
        values[0] = values[1]
    return values


def speed_at_frame(samples: list[RoutePoint], sample_distances: list[float], frame_index: int) -> float | None:
    if frame_index <= 0 or frame_index >= len(samples) or frame_index >= len(sample_distances):
        return None
    current = samples[frame_index]
    previous = samples[frame_index - 1]
    if current.time is None or previous.time is None:
        return None
    seconds = (current.time - previous.time).total_seconds()
    if seconds <= 0:
        return None
    meters = sample_distances[frame_index] - sample_distances[frame_index - 1]
    return meters / seconds * 3.6


def elevation_series(samples: list[RoutePoint]) -> list[float | None]:
    return [sample.elevation for sample in samples]


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
