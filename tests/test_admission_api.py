from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gpx_route_generator.app import create_app
from gpx_route_generator.config import validate_settings
from gpx_route_generator.maps import SolidColorMapClient

from test_api import make_settings, post_render


def test_settings_reject_invalid_render_admission_limits(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    with pytest.raises(ValueError, match="MAX_ACTIVE_RENDERS"):
        validate_settings(replace(settings, max_active_renders=0))
    with pytest.raises(ValueError, match="MAX_QUEUED_RENDERS"):
        validate_settings(replace(settings, max_queued_renders=-1))


def test_render_rejects_request_when_admission_capacity_is_full(tmp_path: Path) -> None:
    settings = replace(
        make_settings(tmp_path),
        max_active_renders=1,
        max_queued_renders=1,
    )
    app = create_app(
        settings=settings,
        map_client_factory=lambda _settings: SolidColorMapClient(),
    )
    held = [app.state.render_admission.enqueue() for _ in range(2)]
    assert all(token is not None for token in held)
    client = TestClient(app)

    response = post_render(client)

    assert response.status_code == 429
    assert response.json()["detail"] == "Render capacity is full. Please try again later."
    assert not settings.jobs_dir.exists()


def test_env_example_documents_render_admission_limits() -> None:
    env_example = Path(__file__).parents[1].joinpath(".env.example").read_text()

    assert "MAX_ACTIVE_RENDERS=1" in env_example
    assert "MAX_QUEUED_RENDERS=2" in env_example


def test_compose_exposes_render_admission_limits() -> None:
    compose = Path(__file__).parents[1].joinpath("docker-compose.yml").read_text()

    assert "MAX_ACTIVE_RENDERS: ${MAX_ACTIVE_RENDERS:-1}" in compose
    assert "MAX_QUEUED_RENDERS: ${MAX_QUEUED_RENDERS:-2}" in compose


def test_load_settings_reads_render_admission_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_ACTIVE_RENDERS", "3")
    monkeypatch.setenv("MAX_QUEUED_RENDERS", "4")
    monkeypatch.chdir(tmp_path)
    from gpx_route_generator.config import load_settings

    settings = load_settings()

    assert settings.max_active_renders == 3
    assert settings.max_queued_renders == 4


def test_load_settings_rejects_invalid_render_admission_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MAX_ACTIVE_RENDERS", "0")
    from gpx_route_generator.config import load_settings

    with pytest.raises(ValueError, match="MAX_ACTIVE_RENDERS"):
        load_settings()


def test_render_admission_uses_configured_limits(tmp_path: Path) -> None:
    settings = replace(
        make_settings(tmp_path),
        max_active_renders=2,
        max_queued_renders=3,
    )
    app = create_app(settings=settings)

    assert app.state.render_admission.capacity == {"active": 2, "queued": 3}
