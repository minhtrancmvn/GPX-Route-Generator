from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from gpx_route_generator.app import create_app
from gpx_route_generator.maps import SolidColorMapClient

from test_api import make_settings, post_render


class FetchOnlyClient(SolidColorMapClient):
    close = None


def test_fetch_only_injected_client_remains_supported(tmp_path: Path) -> None:
    app = create_app(
        settings=make_settings(tmp_path),
        map_client_factory=lambda _settings: FetchOnlyClient(),
    )
    client = TestClient(app)

    response = post_render(client)

    assert response.status_code == 202


def test_close_failure_does_not_mask_successful_render(tmp_path: Path) -> None:
    class CloseFailingClient(SolidColorMapClient):
        def close(self) -> None:
            raise RuntimeError("close failed")

    app = create_app(
        settings=make_settings(tmp_path),
        map_client_factory=lambda _settings: CloseFailingClient(),
    )
    client = TestClient(app)

    response = post_render(client)

    assert response.status_code == 202
    assert response.json()["status"] in {"queued", "completed"}
