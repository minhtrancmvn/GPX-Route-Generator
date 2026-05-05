from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from io import BytesIO
from pathlib import Path
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
        smoothing=options.camera_smoothing,
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
        for index, point in enumerate(samples):
            camera_state = camera_states[index]
            render_options = replace(options, zoom=camera_state.zoom)
            center_x, center_y = camera_state.center_world
            sample_world_pixels = [
                lat_lon_to_world_pixel(sample.lat, sample.lon, render_options.zoom)
                for sample in samples
            ]
            center_lat, center_lon = world_pixel_to_lat_lon(center_x, center_y, render_options.zoom)
            map_bytes = map_client.fetch(center_lat, center_lon, render_options)
            map_requests += 1
            frame = compose_frame(
                map_bytes=map_bytes,
                samples=samples,
                sample_world_pixels=sample_world_pixels,
                sample_distances=sample_distances,
                frame_index=index,
                camera_center_world=(center_x, center_y),
                options=render_options,
            )
            process.stdin.write(frame.convert("RGB").tobytes())
            if progress_callback:
                progress_callback(index + 1, options.frame_count, map_requests)
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
        draw_distance_badge(draw, sample_world_pixels, sample_distances, frame_index, camera_center_world, options)
    draw_arrow(overlay, samples, sample_world_pixels, frame_index, camera_center_world, options)
    if options.show_progress_bar:
        draw_progress_bar(draw, frame_index, options)
    draw_hud(draw, samples, sample_distances, frame_index, options)
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
    arrow = make_arrow(options.arrow_size).rotate(-bearing, expand=True, resample=Image.Resampling.BICUBIC)
    arrow_x, arrow_y = world_to_frame(sample_world_pixels[frame_index], camera_center_world, options)
    x = int(arrow_x - arrow.width / 2)
    y = int(arrow_y - arrow.height / 2)
    overlay.alpha_composite(arrow, (x, y))


def make_arrow(size: int) -> Image.Image:
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
    sample_world_pixels: list[tuple[float, float]],
    sample_distances: list[float],
    frame_index: int,
    camera_center_world: tuple[float, float],
    options: RenderOptions,
) -> None:
    arrow_x, arrow_y = world_to_frame(sample_world_pixels[frame_index], camera_center_world, options)
    text = format_distance(sample_distances[frame_index])
    font = load_font(max(24, int(options.width * 0.045)), bold=True)
    pad_x = max(12, int(options.width * 0.018))
    pad_y = max(7, int(options.width * 0.010))
    bbox = draw.textbbox((0, 0), text, font=font)
    box_w = bbox[2] - bbox[0] + pad_x * 2
    box_h = bbox[3] - bbox[1] + pad_y * 2
    x = clamp(arrow_x - box_w * 0.45, 16, options.width - box_w - 16)
    y = clamp(arrow_y + options.arrow_size * 0.36, 72, options.height - box_h - 72)
    radius = max(8, int(box_h * 0.35))
    draw.rounded_rectangle((x + 3, y + 4, x + box_w + 3, y + box_h + 4), radius=radius, fill=(0, 0, 0, 105))
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=radius, fill=(242, 26, 26, 245))
    draw.text((x + pad_x, y + pad_y - 1), text, fill=(255, 255, 255, 255), font=font)


def draw_hud(
    draw: ImageDraw.ImageDraw,
    samples: list[RoutePoint],
    sample_distances: list[float],
    frame_index: int,
    options: RenderOptions,
) -> None:
    entries: list[str] = []
    elapsed = min(options.duration_seconds, frame_index / options.fps)
    if options.show_time:
        entries.append(f"Time {format_elapsed(elapsed)}")
    if options.show_distance:
        entries.append(f"Distance {format_distance(sample_distances[frame_index])}")
    if options.show_speed:
        entries.append(f"Speed {format_speed(samples, sample_distances, frame_index)}")
    elevation = samples[frame_index].elevation
    if options.show_elevation:
        entries.append(f"Elev {format_elevation(elevation)}")
    if not entries:
        return
    text = "  |  ".join(entries)
    font = load_font(max(18, int(options.width * 0.030)), bold=True)
    padding_x = max(14, int(options.width * 0.020))
    padding_y = max(10, int(options.width * 0.014))
    bbox = draw.textbbox((0, 0), text, font=font)
    box_w = bbox[2] - bbox[0] + padding_x * 2
    box_h = bbox[3] - bbox[1] + padding_y * 2
    x = max(16, int(options.width * 0.030))
    y = max(48, int(options.width * 0.075))
    max_w = options.width - x * 2
    if box_w > max_w:
        lines = split_hud_entries(entries)
        line_bboxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        box_w = min(max_w, max(bbox[2] - bbox[0] for bbox in line_bboxes) + padding_x * 2)
        line_h = max(bbox[3] - bbox[1] for bbox in line_bboxes)
        box_h = line_h * len(lines) + padding_y * 2 + (len(lines) - 1) * 6
        draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=10, fill=(10, 17, 28, 205))
        for line_index, line in enumerate(lines):
            draw.text((x + padding_x, y + padding_y + line_index * (line_h + 6)), line, fill=(255, 255, 255, 245), font=font)
        return
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=10, fill=(10, 17, 28, 205))
    draw.text((x + padding_x, y + padding_y), text, fill=(255, 255, 255, 245), font=font)


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


def format_elapsed(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    minutes, remainder = divmod(total_seconds, 60)
    return f"{minutes}:{remainder:02d}"


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


def split_hud_entries(entries: list[str]) -> list[str]:
    if len(entries) <= 2:
        return ["  |  ".join(entries)]
    midpoint = (len(entries) + 1) // 2
    return ["  |  ".join(entries[:midpoint]), "  |  ".join(entries[midpoint:])]


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
