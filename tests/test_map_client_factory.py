from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from gpx_route_generator.app import create_app
from gpx_route_generator.maps import SolidColorMapClient

from test_api import VALID_GPX, make_settings


def test_injected_shared_map_client_is_not_closed_per_request(tmp_path: Path) -> None:
    class SharedClient(SolidColorMapClient):
        def __init__(self) -> None:
            super().__init__()
            self.closed = False

        def close(self) -> None:
            self.closed = True

    shared = SharedClient()
    app = create_app(
        settings=make_settings(tmp_path),
        map_client_factory=lambda _settings: shared,
    )
    client = TestClient(app)
    files = {"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")}
    data = {"duration_seconds": "5", "fps": "1"}

    first = client.post("/api/preview", files=files, data=data)
    second = client.post("/api/preview", files=files, data=data)

    assert first.status_code == 200
    assert second.status_code == 200
    assert shared.closed is False
