from __future__ import annotations

import math
from io import StringIO

import gpxpy
import gpxpy.gpx

from .geo import cumulative_distances
from .models import RoutePoint


def parse_gpx_bytes(data: bytes, *, max_points: int | None = None) -> list[RoutePoint]:
    if not data:
        raise ValueError("Upload a GPX file before rendering.")
    try:
        text = data.decode("utf-8-sig")
        gpx = gpxpy.parse(StringIO(text))
    except Exception as exc:
        raise ValueError("The uploaded file is not a valid GPX document.") from exc

    points: list[RoutePoint] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                lat = point.latitude
                lon = point.longitude
                if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                    raise ValueError("GPX route contains an invalid coordinate.")
                if max_points is not None and len(points) >= max_points:
                    raise ValueError(f"GPX route exceeds the maximum of {max_points} track points.")
                points.append(
                    RoutePoint(
                        lat=lat,
                        lon=lon,
                        elevation=point.elevation,
                        time=point.time,
                    )
                )

    if len(points) < 2:
        raise ValueError("GPX route must contain at least two track points.")
    if cumulative_distances(points)[-1] <= 0:
        raise ValueError("GPX route must cover a non-zero distance.")
    return points

