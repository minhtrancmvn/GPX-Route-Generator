"""Plan and crop reusable Google Static Maps source images for a render."""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .geo import CameraState, lat_lon_to_world_pixel, world_pixel_to_lat_lon
from .models import RenderOptions

MAX_MAP_SEGMENTS = 12
SOURCE_STATIC_SIZE = (640, 640)
SAFE_MARGIN_RATIO = 0.15


@dataclass(frozen=True)
class MapSegment:
    id: int
    frame_start: int
    frame_end: int
    source_zoom: int
    center_world: tuple[float, float]
    source_bounds: tuple[float, float, float, float]

    @property
    def center_lat_lon(self) -> tuple[float, float]:
        return world_pixel_to_lat_lon(*self.center_world, self.source_zoom)


@dataclass(frozen=True)
class MapSegmentPlan:
    camera_states: tuple[CameraState, ...]
    segments: tuple[MapSegment, ...]
    frame_segment_ids: tuple[int, ...]

    @property
    def map_request_count(self) -> int:
        return len(self.segments)

    def segment_for_frame(self, frame_index: int) -> MapSegment:
        return self.segments[self.frame_segment_ids[frame_index]]


def build_map_segment_plan(
    camera_states: list[CameraState],
    options: RenderOptions,
    max_segments: int = MAX_MAP_SEGMENTS,
    safe_margin_ratio: float = SAFE_MARGIN_RATIO,
) -> MapSegmentPlan:
    """Build overlapping source-image segments, widening the camera only when needed."""
    if not camera_states:
        return MapSegmentPlan(camera_states=(), segments=(), frame_segment_ids=())
    if max_segments < 1:
        raise ValueError("Map segment limit must be at least one.")
    if not 0 <= safe_margin_ratio < 0.5:
        raise ValueError("Map segment safe margin must be between 0 and 0.5.")

    target_zoom = min(state.zoom for state in camera_states)
    while target_zoom >= 1:
        states = _with_zoom(camera_states, target_zoom)
        source_zoom = max(0, target_zoom - 1)
        segments, frame_segment_ids = _build_segments(states, source_zoom, options, safe_margin_ratio)
        if len(segments) <= max_segments:
            return MapSegmentPlan(
                camera_states=tuple(states),
                segments=tuple(segments),
                frame_segment_ids=tuple(frame_segment_ids),
            )
        target_zoom -= 1

    raise ValueError(f"Route needs more than {max_segments} Google Static Map images at the widest supported zoom.")


def prepare_segment_frame(
    source_image: Image.Image,
    segment: MapSegment,
    camera_state: CameraState,
    options: RenderOptions,
) -> Image.Image:
    """Crop one output viewport from a pre-fetched source image."""
    left, top, right, bottom = _frame_bounds(camera_state, segment.source_zoom, options)
    source_left, source_top, source_right, source_bottom = segment.source_bounds
    if left < source_left or top < source_top or right > source_right or bottom > source_bottom:
        raise ValueError(f"Frame camera is outside planned map segment {segment.id}.")

    source_width, source_height = segment_size_pixels(options)
    bounds_width = source_right - source_left
    bounds_height = source_bottom - source_top
    crop = (
        round((left - source_left) / bounds_width * source_width),
        round((top - source_top) / bounds_height * source_height),
        round((right - source_left) / bounds_width * source_width),
        round((bottom - source_top) / bounds_height * source_height),
    )
    return source_image.crop(crop).resize((options.width, options.height), Image.Resampling.LANCZOS)


def segment_size_pixels(options: RenderOptions) -> tuple[int, int]:
    return tuple(dimension * options.scale for dimension in SOURCE_STATIC_SIZE)


def _with_zoom(camera_states: list[CameraState], zoom: int) -> list[CameraState]:
    states: list[CameraState] = []
    for state in camera_states:
        lat, lon = world_pixel_to_lat_lon(*state.center_world, state.zoom)
        states.append(CameraState(zoom=zoom, center_world=lat_lon_to_world_pixel(lat, lon, zoom)))
    return states


def _build_segments(
    camera_states: list[CameraState],
    source_zoom: int,
    options: RenderOptions,
    safe_margin_ratio: float,
) -> tuple[list[MapSegment], list[int]]:
    source_width, source_height = SOURCE_STATIC_SIZE
    if options.width / options.scale > source_width or options.height / options.scale > source_height:
        raise ValueError("Output viewport is larger than a Google Static Map source image.")
    margin_x = source_width * safe_margin_ratio
    margin_y = source_height * safe_margin_ratio
    max_content_width = source_width - margin_x * 2
    max_content_height = source_height - margin_y * 2

    segments: list[MapSegment] = []
    frame_segment_ids: list[int] = []
    frame_start = 0
    bounds = _frame_bounds(camera_states[0], source_zoom, options)

    for frame_index, state in enumerate(camera_states[1:], start=1):
        candidate = _combine_bounds(bounds, _frame_bounds(state, source_zoom, options))
        if _bounds_width(candidate) <= max_content_width and _bounds_height(candidate) <= max_content_height:
            bounds = candidate
            continue

        segment = _make_segment(
            id=len(segments),
            frame_start=frame_start,
            frame_end=frame_index - 1,
            content_bounds=bounds,
            source_zoom=source_zoom,
            margin_x=margin_x,
            margin_y=margin_y,
        )
        segments.append(segment)
        frame_segment_ids.extend([segment.id] * (frame_index - frame_start))
        frame_start = frame_index
        bounds = _frame_bounds(state, source_zoom, options)

    segment = _make_segment(
        id=len(segments),
        frame_start=frame_start,
        frame_end=len(camera_states) - 1,
        content_bounds=bounds,
        source_zoom=source_zoom,
        margin_x=margin_x,
        margin_y=margin_y,
    )
    segments.append(segment)
    frame_segment_ids.extend([segment.id] * (len(camera_states) - frame_start))
    return segments, frame_segment_ids


def _make_segment(
    *,
    id: int,
    frame_start: int,
    frame_end: int,
    content_bounds: tuple[float, float, float, float],
    source_zoom: int,
    margin_x: float,
    margin_y: float,
) -> MapSegment:
    content_left, content_top, content_right, content_bottom = content_bounds
    source_width, source_height = SOURCE_STATIC_SIZE
    center_world = ((content_left + content_right) / 2, (content_top + content_bottom) / 2)
    source_bounds = (
        center_world[0] - source_width / 2,
        center_world[1] - source_height / 2,
        center_world[0] + source_width / 2,
        center_world[1] + source_height / 2,
    )
    if content_left < source_bounds[0] + margin_x or content_right > source_bounds[2] - margin_x:
        raise ValueError("Map segment horizontal coverage is insufficient.")
    if content_top < source_bounds[1] + margin_y or content_bottom > source_bounds[3] - margin_y:
        raise ValueError("Map segment vertical coverage is insufficient.")
    return MapSegment(
        id=id,
        frame_start=frame_start,
        frame_end=frame_end,
        source_zoom=source_zoom,
        center_world=center_world,
        source_bounds=source_bounds,
    )


def _frame_bounds(
    camera_state: CameraState,
    source_zoom: int,
    options: RenderOptions,
) -> tuple[float, float, float, float]:
    center_lat, center_lon = world_pixel_to_lat_lon(*camera_state.center_world, camera_state.zoom)
    center_x, center_y = lat_lon_to_world_pixel(center_lat, center_lon, source_zoom)
    zoom_ratio = 2 ** (camera_state.zoom - source_zoom)
    half_width = options.width / options.scale / zoom_ratio / 2
    half_height = options.height / options.scale / zoom_ratio / 2
    return (center_x - half_width, center_y - half_height, center_x + half_width, center_y + half_height)


def _combine_bounds(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    return (
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[2], second[2]),
        max(first[3], second[3]),
    )


def _bounds_width(bounds: tuple[float, float, float, float]) -> float:
    return bounds[2] - bounds[0]


def _bounds_height(bounds: tuple[float, float, float, float]) -> float:
    return bounds[3] - bounds[1]
