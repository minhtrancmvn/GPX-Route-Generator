from __future__ import annotations

from io import StringIO

import gpxpy
import gpxpy.gpx

from .geo import cumulative_distances
from .models import RoutePoint


def parse_gpx_bytes(data: bytes) -> list[RoutePoint]:
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
                points.append(
                    RoutePoint(
                        lat=point.latitude,
                        lon=point.longitude,
                        elevation=point.elevation,
                        time=point.time,
                    )
                )

    if len(points) < 2:
        raise ValueError("GPX route must contain at least two track points.")
    if cumulative_distances(points)[-1] <= 0:
        raise ValueError("GPX route must cover a non-zero distance.")
    return points

