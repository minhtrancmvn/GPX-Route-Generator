from __future__ import annotations

import pytest

from gpx_route_generator.gpx import parse_gpx_bytes

VALID_GPX = b"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="pytest" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>Sample</name>
    <trkseg>
      <trkpt lat="37.0000" lon="-122.0000"><ele>10</ele></trkpt>
      <trkpt lat="37.0005" lon="-122.0002"><ele>11</ele></trkpt>
      <trkpt lat="37.0010" lon="-122.0004"><ele>12</ele></trkpt>
    </trkseg>
  </trk>
</gpx>
"""


def make_gpx_bytes(point_count: int, *, first: tuple[float, float] = (37.0, -122.0)) -> bytes:
    points = []
    for index in range(point_count):
        lat, lon = first if index == 0 else (37.0 + index * 0.0005, -122.0 - index * 0.0002)
        points.append(f'      <trkpt lat="{lat}" lon="{lon}" />')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="pytest" xmlns="http://www.topografix.com/GPX/1/1">\n'
        "  <trk><trkseg>\n" + "\n".join(points) + "\n  </trkseg></trk>\n</gpx>\n"
    ).encode()


def test_parse_gpx_bytes_extracts_track_points() -> None:
    points = parse_gpx_bytes(VALID_GPX)
    assert len(points) == 3
    assert points[0].lat == pytest.approx(37.0)
    assert points[0].lon == pytest.approx(-122.0)
    assert points[0].elevation == pytest.approx(10)


def test_parse_gpx_rejects_invalid_xml() -> None:
    with pytest.raises(ValueError, match="valid GPX"):
        parse_gpx_bytes(b"not a gpx file")


def test_parse_gpx_rejects_empty_route() -> None:
    empty = b"""<gpx version="1.1" creator="pytest" xmlns="http://www.topografix.com/GPX/1/1"></gpx>"""
    with pytest.raises(ValueError, match="at least two"):
        parse_gpx_bytes(empty)


def test_parse_gpx_accepts_configured_point_limit() -> None:
    points = parse_gpx_bytes(make_gpx_bytes(4), max_points=4)
    assert len(points) == 4


def test_parse_gpx_rejects_point_above_limit() -> None:
    with pytest.raises(ValueError, match="maximum.*4"):
        parse_gpx_bytes(make_gpx_bytes(5), max_points=4)


@pytest.mark.parametrize(
    ("lat", "lon"),
    [(float("nan"), -122.0), (float("inf"), -122.0), (37.0, 180.1), (90.1, -122.0)],
)
def test_parse_gpx_rejects_invalid_coordinates(lat: float, lon: float) -> None:
    with pytest.raises(ValueError, match="coordinate"):
        parse_gpx_bytes(make_gpx_bytes(2, first=(lat, lon)))

