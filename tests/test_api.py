from __future__ import annotations

from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient
import requests

from gpx_route_generator.app import create_app
from gpx_route_generator.config import Settings
from gpx_route_generator.maps import SolidColorMapClient

VALID_GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="pytest" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="37.0000" lon="-122.0000"><ele>10</ele></trkpt>
    <trkpt lat="37.0010" lon="-122.0006"><ele>12</ele></trkpt>
  </trkseg></trk>
</gpx>
"""


def make_settings(tmp_path: Path, api_key: str | None = "test-key") -> Settings:
    return Settings(
        google_maps_api_key=api_key,
        google_maps_signature_secret=None,
        environment="local",
        recaptcha_site_key=None,
        recaptcha_secret_key=None,
        jobs_dir=tmp_path / "jobs",
        ffmpeg_path="ffmpeg",
    )


def post_render(client: TestClient, **overrides):
    data = {
        "output_format": "landscape",
        "duration_seconds": "5",
        "fps": "1",
        "zoom": "14",
        "map_type": "roadmap",
        "trail_color": "#ff2f2f",
        "trail_width": "6",
        "arrow_size": "54",
        "avatar_id": "mt15",
        "camera_smoothing": "0.72",
        "show_progress_bar": "true",
        "show_distance": "true",
        "show_speed": "true",
        "show_elevation": "true",
    }
    data.update(overrides)
    return client.post(
        "/api/render",
        data=data,
        files={"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")},
    )


def test_render_requires_google_api_key(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path, api_key=None))
    client = TestClient(app)
    response = post_render(client)
    assert response.status_code == 400
    assert "GOOGLE_MAPS_API_KEY" in response.json()["detail"]


def test_index_page_loads(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path, api_key=None))
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "GPX Route Generator" in response.text
    assert "Avatar size" in response.text
    assert "3D globe" not in response.text
    assert "Time" not in response.text
    assert "recaptcha/api.js" not in response.text

def test_index_page_loads_recaptcha_in_production(tmp_path: Path) -> None:
    settings = Settings(
        google_maps_api_key="test-key",
        google_maps_signature_secret=None,
        environment="production",
        recaptcha_site_key="site-key",
        recaptcha_secret_key="secret-key",
        jobs_dir=tmp_path / "jobs",
        ffmpeg_path="ffmpeg",
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "recaptcha/api.js?render=site-key" in response.text


def test_avatar_preview_loads_without_google_api_key(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path, api_key=None))
    client = TestClient(app)
    response = client.get("/api/avatars/default/preview?size=64")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")

def test_preview_frame_uses_single_map_request(tmp_path: Path) -> None:
    map_client = SolidColorMapClient()
    app = create_app(settings=make_settings(tmp_path), map_client_factory=lambda settings: map_client)
    client = TestClient(app)
    response = client.post(
        "/api/preview",
        data={
            "render_mode": "video2d",
            "output_format": "landscape",
            "duration_seconds": "5",
            "fps": "1",
            "zoom": "14",
            "map_type": "roadmap",
            "trail_color": "#ff2f2f",
            "trail_width": "6",
            "arrow_size": "54",
            "avatar_id": "default",
            "show_progress_bar": "true",
            "show_distance": "true",
            "show_speed": "true",
            "show_elevation": "true",
        },
        files={"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
    assert map_client.requests == 1


def test_render_validates_duration(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path))
    client = TestClient(app)
    response = post_render(client, duration_seconds="4")
    assert response.status_code == 422
    assert "Duration" in response.json()["detail"]


def test_render_validates_avatar(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path))
    client = TestClient(app)
    response = post_render(client, avatar_id="unknown")
    assert response.status_code == 422
    assert "Avatar" in response.json()["detail"]


def test_render_requires_recaptcha_in_production(tmp_path: Path) -> None:
    settings = Settings(
        google_maps_api_key="test-key",
        google_maps_signature_secret=None,
        environment="production",
        recaptcha_site_key="site-key",
        recaptcha_secret_key="secret-key",
        jobs_dir=tmp_path / "jobs",
        ffmpeg_path="ffmpeg",
    )
    app = create_app(settings=settings)
    client = TestClient(app)
    response = post_render(client)
    assert response.status_code == 400
    assert "reCAPTCHA verification is required" in response.json()["detail"]

def test_render_accepts_valid_recaptcha_in_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        google_maps_api_key="test-key",
        google_maps_signature_secret=None,
        environment="production",
        recaptcha_site_key="site-key",
        recaptcha_secret_key="secret-key",
        jobs_dir=tmp_path / "jobs",
        ffmpeg_path="ffmpeg",
    )

    class MockResponse:
        def json(self):
            return {"success": True, "score": 0.9}

    def fake_post(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    map_client = SolidColorMapClient()
    app = create_app(settings=settings, map_client_factory=lambda settings: map_client)
    client = TestClient(app)
    response = post_render(client, recaptcha_token="token")
    assert response.status_code == 200

def test_render_rejects_low_recaptcha_score_in_production(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        google_maps_api_key="test-key",
        google_maps_signature_secret=None,
        environment="production",
        recaptcha_site_key="site-key",
        recaptcha_secret_key="secret-key",
        jobs_dir=tmp_path / "jobs",
        ffmpeg_path="ffmpeg",
    )

    class MockResponse:
        def json(self):
            return {"success": True, "score": 0.4}

    def fake_post(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    app = create_app(settings=settings)
    client = TestClient(app)
    response = post_render(client, recaptcha_token="token")
    assert response.status_code == 403
    assert "reCAPTCHA score is too low" in response.json()["detail"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_render_job_completes_with_mocked_maps(tmp_path: Path) -> None:
    map_client = SolidColorMapClient()
    app = create_app(settings=make_settings(tmp_path), map_client_factory=lambda settings: map_client)
    client = TestClient(app)

    response = post_render(client)

    assert response.status_code == 200
    job_id = response.json()["id"]
    status = client.get(f"/api/jobs/{job_id}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "completed"
    assert payload["progress"] == 1
    assert 1 <= payload["actual_map_requests"] < 5
    assert map_client.requests == payload["actual_map_requests"]

    video = client.get(f"/api/jobs/{job_id}/video")
    assert video.status_code == 200
    assert video.headers["content-type"].startswith("video/mp4")
    assert len(video.content) > 0
