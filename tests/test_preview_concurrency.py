from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import asyncio
import time
from threading import Event, Thread

import httpx
import pytest
from fastapi.testclient import TestClient

import gpx_route_generator.app as app_module
from gpx_route_generator.app import create_app
from gpx_route_generator.config import validate_settings
from gpx_route_generator.maps import SolidColorMapClient

from test_api import VALID_GPX, make_settings


def post_preview(client: TestClient):
    return client.post(
        "/api/preview",
        files={"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")},
        data={"duration_seconds": "5", "fps": "1"},
    )


def test_settings_reject_invalid_preview_limit(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="MAX_ACTIVE_PREVIEWS"):
        validate_settings(replace(make_settings(tmp_path), max_active_previews=0))


def test_preview_rejects_when_concurrency_limit_is_full(
    tmp_path: Path, monkeypatch
) -> None:
    settings = replace(make_settings(tmp_path), max_active_previews=1)
    app = create_app(
        settings=settings,
        map_client_factory=lambda _settings: SolidColorMapClient(),
    )
    client = TestClient(app)
    started = Event()
    release = Event()
    real_render = app_module.render_preview_frame_2d

    def slow_render(*args, **kwargs):
        started.set()
        release.wait(timeout=1)
        return real_render(*args, **kwargs)

    monkeypatch.setattr(app_module, "render_preview_frame_2d", slow_render)
    first_response: list[object] = []
    thread = Thread(target=lambda: first_response.append(post_preview(client)))
    thread.start()
    assert started.wait(timeout=0.5)

    second = post_preview(client)
    release.set()
    thread.join(timeout=2)

    assert second.status_code == 429
    assert second.json()["detail"] == "Preview capacity is full. Please try again later."
    assert first_response[0].status_code == 200


def test_slow_preview_does_not_block_config_endpoint(tmp_path: Path, monkeypatch) -> None:
    app = create_app(
        settings=make_settings(tmp_path),
        map_client_factory=lambda _settings: SolidColorMapClient(),
    )
    started = Event()
    release = Event()
    real_render = app_module.render_preview_frame_2d

    def slow_render(*args, **kwargs):
        started.set()
        release.wait(timeout=1)
        return real_render(*args, **kwargs)

    monkeypatch.setattr(app_module, "render_preview_frame_2d", slow_render)

    async def scenario() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            preview = asyncio.create_task(
                client.post(
                    "/api/preview",
                    files={"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")},
                    data={"duration_seconds": "5", "fps": "1"},
                )
            )
            await asyncio.to_thread(started.wait, 0.5)
            before = time.monotonic()
            response = await client.get("/api/config")
            elapsed = time.monotonic() - before
            release.set()
            await preview
            assert response.status_code == 200
            return elapsed

    assert asyncio.run(scenario()) < 0.2


def test_slow_recaptcha_does_not_block_config_endpoint(tmp_path: Path, monkeypatch) -> None:
    settings = replace(
        make_settings(tmp_path),
        environment="production",
        recaptcha_site_key="site",
        recaptcha_secret_key="secret",
    )
    app = create_app(settings=settings)
    started = Event()
    release = Event()
    def slow_post(*args, **kwargs):
        started.set()
        release.wait(timeout=1)
        return type("Response", (), {"raise_for_status": lambda self: None, "json": lambda self: {"success": True, "score": 1}})()

    monkeypatch.setattr(app_module.requests, "post", slow_post)

    async def scenario() -> float:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            render = asyncio.create_task(client.post("/api/render", data={"recaptcha_token": "token"}))
            await asyncio.to_thread(started.wait, 0.5)
            before = time.monotonic()
            response = await client.get("/api/config")
            elapsed = time.monotonic() - before
            release.set()
            await render
            assert response.status_code == 200
            return elapsed

    assert asyncio.run(scenario()) < 0.2


def test_preview_slot_releases_after_failure(tmp_path: Path, monkeypatch) -> None:
    settings = replace(make_settings(tmp_path), max_active_previews=1)
    app = create_app(
        settings=settings,
        map_client_factory=lambda _settings: SolidColorMapClient(),
    )
    client = TestClient(app)
    calls = 0
    real_render = app_module.render_preview_frame_2d

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("preview failed")
        return real_render(*args, **kwargs)

    monkeypatch.setattr(app_module, "render_preview_frame_2d", fail_once)

    assert post_preview(client).status_code == 500
    assert post_preview(client).status_code == 200
