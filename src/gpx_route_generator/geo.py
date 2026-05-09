from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
import math

from .models import RoutePoint

EARTH_RADIUS_M = 6_371_000
MAX_MERCATOR_LAT = 85.05112878
TILE_SIZE = 256


@dataclass(frozen=True)
class CameraState:
    zoom: int
    center_world: tuple[float, float]


def clamp_lat(lat: float) -> float:
    return max(-MAX_MERCATOR_LAT, min(MAX_MERCATOR_LAT, lat))


def lat_lon_to_world_pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    lat = clamp_lat(lat)
    world_size = TILE_SIZE * (2**zoom)
    x = (lon + 180.0) / 360.0 * world_size
    sin_lat = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * world_size
    return x, y


def world_pixel_to_lat_lon(x: float, y: float, zoom: int) -> tuple[float, float]:
    world_size = TILE_SIZE * (2**zoom)
    lon = x / world_size * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / world_size
    lat = math.degrees(math.atan(math.sinh(n)))
    return lat, lon


def project_to_frame(
    point_lat: float,
    point_lon: float,
    center_lat: float,
    center_lon: float,
    zoom: int,
    width: int,
    height: int,
    scale: int = 2,
) -> tuple[float, float]:
    px, py = lat_lon_to_world_pixel(point_lat, point_lon, zoom)
    cx, cy = lat_lon_to_world_pixel(center_lat, center_lon, zoom)
    return ((px - cx) * scale + width / 2, (py - cy) * scale + height / 2)


def route_world_bounds(points: list[RoutePoint], zoom: int) -> tuple[float, float, float, float]:
    pixels = [lat_lon_to_world_pixel(point.lat, point.lon, zoom) for point in points]
    xs = [pixel[0] for pixel in pixels]
    ys = [pixel[1] for pixel in pixels]
    return min(xs), min(ys), max(xs), max(ys)


def route_center_world_pixel(points: list[RoutePoint], zoom: int) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = route_world_bounds(points, zoom)
    return (min_x + max_x) / 2, (min_y + max_y) / 2


def fit_overview_zoom(
    points: list[RoutePoint],
    max_zoom: int,
    width: int,
    height: int,
    scale: int = 2,
    padding_ratio: float = 0.14,
    context_zoom_out: int = 0,
    min_zoom: int = 1,
) -> int:
    if len(points) < 2:
        return max(min_zoom, min(max_zoom, 21))
    padding_ratio = max(0.0, min(0.45, padding_ratio))
    usable_width = width * (1 - padding_ratio * 2)
    usable_height = height * (1 - padding_ratio * 2)
    selected_zoom = min(max_zoom, 21)
    for zoom in range(min(max_zoom, 21), min_zoom - 1, -1):
        min_x, min_y, max_x, max_y = route_world_bounds(points, zoom)
        route_width = max(1.0, (max_x - min_x) * scale)
        route_height = max(1.0, (max_y - min_y) * scale)
        if route_width <= usable_width and route_height <= usable_height:
            selected_zoom = zoom
            break
    return max(min_zoom, selected_zoom - context_zoom_out)


def local_route_window_points(
    points: list[RoutePoint],
    distances: list[float],
    index: int,
    window_meters: float,
    future_ratio: float = 0.65,
) -> list[RoutePoint]:
    if not points:
        return []
    if len(points) != len(distances):
        raise ValueError("Points and distances must have the same length.")
    current_distance = distances[index]
    future_ratio = max(0.2, min(0.8, future_ratio))
    start_distance = current_distance - window_meters * (1 - future_ratio)
    end_distance = current_distance + window_meters * future_ratio
    window = [
        point
        for point, distance in zip(points, distances)
        if start_distance <= distance <= end_distance
    ]
    if points[index] not in window:
        window.append(points[index])
    if len(window) < 2 and len(points) > 1:
        neighbor_index = index + 1 if index == 0 else index - 1
        window.append(points[neighbor_index])
    return window or [points[index]]


def dynamic_route_window_meters(total_distance_meters: float, duration_seconds: float = 10.0) -> float:
    """Compute local camera window based on playback speed.

    Faster playback (long trip, short duration) → bigger window → wider view.
    Slower playback (short trip, long duration) → smaller window → zoomed closer.
    """
    if total_distance_meters <= 0:
        return 1_500
    meters_per_second = total_distance_meters / max(1.0, duration_seconds)
    # Show ~2.5 s of content in the local window
    window = meters_per_second * 2.5
    return max(1_000, min(50_000, window))


def haversine_meters(a: RoutePoint, b: RoutePoint) -> float:
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def cumulative_distances(points: list[RoutePoint]) -> list[float]:
    distances = [0.0]
    for previous, current in zip(points, points[1:]):
        distances.append(distances[-1] + haversine_meters(previous, current))
    return distances


def interpolate_point(a: RoutePoint, b: RoutePoint, ratio: float) -> RoutePoint:
    ratio = max(0.0, min(1.0, ratio))
    elevation = None
    if a.elevation is not None and b.elevation is not None:
        elevation = a.elevation + (b.elevation - a.elevation) * ratio
    time = None
    if a.time is not None and b.time is not None:
        time = a.time + (b.time - a.time) * ratio
    return RoutePoint(
        lat=a.lat + (b.lat - a.lat) * ratio,
        lon=a.lon + (b.lon - a.lon) * ratio,
        elevation=elevation,
        time=time,
    )


def resample_by_distance(points: list[RoutePoint], count: int) -> tuple[list[RoutePoint], list[float]]:
    if count < 1:
        raise ValueError("Sample count must be at least one.")
    if len(points) < 2:
        raise ValueError("GPX route must contain at least two points.")

    distances = cumulative_distances(points)
    total = distances[-1]
    if total <= 0:
        raise ValueError("GPX route must cover a non-zero distance.")
    if count == 1:
        return [points[0]], [0.0]

    samples: list[RoutePoint] = []
    sample_distances: list[float] = []
    segment_index = 1
    for sample_index in range(count):
        target = total * sample_index / (count - 1)
        while segment_index < len(distances) - 1 and distances[segment_index] < target:
            segment_index += 1
        previous_distance = distances[segment_index - 1]
        next_distance = distances[segment_index]
        segment_length = next_distance - previous_distance
        ratio = 0.0 if segment_length == 0 else (target - previous_distance) / segment_length
        samples.append(interpolate_point(points[segment_index - 1], points[segment_index], ratio))
        sample_distances.append(target)
    return samples, sample_distances


def compute_bearing_degrees(a: RoutePoint, b: RoutePoint) -> float:
    dlon = math.radians(b.lon - a.lon)
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return math.degrees(math.atan2(x, y)) % 360


def smooth_camera_world_pixels(points: list[RoutePoint], zoom: int, smoothing: float) -> list[tuple[float, float]]:
    if not points:
        return []
    smoothing = max(0.0, min(0.95, smoothing))
    targets = [lat_lon_to_world_pixel(point.lat, point.lon, zoom) for point in points]
    centers = [targets[0]]
    for target_x, target_y in targets[1:]:
        previous_x, previous_y = centers[-1]
        centers.append(
            (
                previous_x * smoothing + target_x * (1 - smoothing),
                previous_y * smoothing + target_y * (1 - smoothing),
            )
        )
    return centers


def overview_camera_world_pixels(
    points: list[RoutePoint],
    zoom: int,
    smoothing: float,
    follow_ratio: float = 0.12,
) -> list[tuple[float, float]]:
    if not points:
        return []
    route_center_x, route_center_y = route_center_world_pixel(points, zoom)
    follow_ratio = max(0.0, min(0.5, follow_ratio))
    smoothed_follow = smooth_camera_world_pixels(points, zoom, smoothing)
    return [
        (
            route_center_x * (1 - follow_ratio) + follow_x * follow_ratio,
            route_center_y * (1 - follow_ratio) + follow_y * follow_ratio,
        )
        for follow_x, follow_y in smoothed_follow
    ]


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def apply_zoom_transitions(
    states: list[CameraState],
    overview_zoom: int,
    overview_center_world: tuple[float, float],
    transition_frames: int,
) -> list[CameraState]:
    """Blend zoom smoothly at start (zoom-in) and end (zoom-out).

    The camera center stays locked on the avatar at all times — only the zoom
    level is interpolated so the avatar never drifts off-centre.
    """
    n = len(states)
    if n == 0 or transition_frames <= 0:
        return states
    t_frames = min(transition_frames, n // 2)
    result: list[CameraState] = []
    for i, state in enumerate(states):
        if i < t_frames:
            ease = _smoothstep(i / t_frames)
        elif i >= n - t_frames:
            ease = _smoothstep((n - 1 - i) / t_frames)
        else:
            ease = 1.0
        # Interpolate zoom only; center stays on the avatar (state.center_world
        # is already expressed at state.zoom, so re-project to blended_zoom).
        blended_zoom = max(1, round(overview_zoom * (1.0 - ease) + state.zoom * ease))
        avatar_lat, avatar_lon = world_pixel_to_lat_lon(*state.center_world, state.zoom)
        blended_center = lat_lon_to_world_pixel(avatar_lat, avatar_lon, blended_zoom)
        result.append(CameraState(zoom=blended_zoom, center_world=blended_center))
    return result


def dynamic_camera_states(
    points: list[RoutePoint],
    distances: list[float],
    width: int,
    height: int,
    scale: int = 2,
    max_zoom: int = 18,
    duration_seconds: float = 10.0,
    fps: int = 24,
) -> list[CameraState]:
    if not points:
        return []
    total_distance = distances[-1] if distances else 0
    window_meters = dynamic_route_window_meters(total_distance, duration_seconds)

    # Compute a single consistent zoom from the middle of the route's window.
    mid = len(points) // 2
    sample_window = local_route_window_points(points, distances, mid, window_meters)
    zoom = fit_overview_zoom(
        sample_window,
        max_zoom=max_zoom,
        width=width,
        height=height,
        scale=scale,
        padding_ratio=0.06,
        min_zoom=1,
    )

    target_states: list[CameraState] = []
    for index in range(len(points)):
        window = local_route_window_points(points, distances, index, window_meters)
        center = route_center_world_pixel(window, zoom)
        point_center = lat_lon_to_world_pixel(points[index].lat, points[index].lon, zoom)
        blended_center = (
            center[0] * 0.45 + point_center[0] * 0.55,
            center[1] * 0.45 + point_center[1] * 0.55,
        )
        target_states.append(CameraState(zoom=zoom, center_world=blended_center))

    return target_states


def with_elapsed_times(samples: list[RoutePoint], duration_seconds: float) -> list[RoutePoint]:
    if not samples or samples[0].time is not None:
        return samples
    start = samples[0].time
    if start is None:
        return samples
    if len(samples) == 1:
        return samples
    return [
        replace(point, time=start + timedelta(seconds=duration_seconds * index / (len(samples) - 1)))
        for index, point in enumerate(samples)
    ]
