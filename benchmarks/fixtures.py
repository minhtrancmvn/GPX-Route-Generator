from __future__ import annotations

from gpx_route_generator.models import RoutePoint


def make_route(point_count: int) -> list[RoutePoint]:
    if point_count < 2:
        raise ValueError("point_count must be at least two")
    return [
        RoutePoint(
            lat=37.0 + index * 0.0001,
            lon=-122.0 - index * 0.00008,
            elevation=10.0 + index,
        )
        for index in range(point_count)
    ]
