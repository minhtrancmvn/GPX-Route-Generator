from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from gpx_route_generator.app import create_app
from gpx_route_generator.maps import SolidColorMapClient

from test_api import VALID_GPX, make_settings, post_render


def test_preview_returns_429_with_retry_after(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), preview_requests_per_minute=1)
    app = create_app(
        settings=settings,
        map_client_factory=lambda _settings: SolidColorMapClient(),
    )
    client = TestClient(app)
    files = {"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")}

    first = client.post("/api/preview", files=files)
    second = client.post("/api/preview", files=files)

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1


def test_render_limit_is_separate_from_preview_limit(tmp_path: Path) -> None:
    settings = replace(
        make_settings(tmp_path),
        preview_requests_per_minute=1,
        render_requests_per_minute=1,
    )
    app = create_app(
        settings=settings,
        map_client_factory=lambda _settings: SolidColorMapClient(),
    )
    client = TestClient(app)
    files = {"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")}
    client.post("/api/preview", files=files)

    response = post_render(client)

    assert response.status_code == 202


def test_render_returns_429_with_retry_after(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), render_requests_per_minute=1)
    app = create_app(
        settings=settings,
        map_client_factory=lambda _settings: SolidColorMapClient(),
    )
    client = TestClient(app)

    first = post_render(client)
    second = post_render(client)

    assert first.status_code == 202
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
