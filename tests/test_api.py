from __future__ import annotations

import logging
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from gpx_route_generator.app import create_app
from gpx_route_generator.config import Settings
from gpx_route_generator.jobs import RenderJob
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


def test_parse_rejects_oversized_upload(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), max_upload_bytes=32)
    client = TestClient(create_app(settings=settings))
    response = client.post(
        "/api/gpx/parse",
        files={"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "GPX upload is too large."


def test_parse_rejects_route_above_point_limit(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), max_route_points=2)
    route_above_limit = VALID_GPX.replace(
        "  </trkseg></trk>",
        '    <trkpt lat="37.0020" lon="-122.0012"><ele>14</ele></trkpt>\n  </trkseg></trk>',
    )
    client = TestClient(create_app(settings=settings))
    response = client.post(
        "/api/gpx/parse",
        files={"gpx_file": ("route.gpx", route_above_limit, "application/gpx+xml")},
    )
    assert response.status_code == 422
    assert "maximum" in response.json()["detail"]


def test_parse_rejects_invalid_coordinates(tmp_path: Path) -> None:
    invalid_gpx = VALID_GPX.replace('lat="37.0000"', 'lat="90.1"')
    client = TestClient(create_app(settings=make_settings(tmp_path)))
    response = client.post(
        "/api/gpx/parse",
        files={"gpx_file": ("route.gpx", invalid_gpx, "application/gpx+xml")},
    )
    assert response.status_code == 422
    assert "coordinate" in response.json()["detail"]


def test_create_app_rejects_unprotected_production(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), environment="production")
    with pytest.raises(ValueError, match="Production requires"):
        create_app(settings=settings)


def test_create_app_allows_explicit_unprotected_production(tmp_path: Path) -> None:
    settings = replace(
        make_settings(tmp_path),
        environment="production",
        allow_unprotected_rendering=True,
    )
    assert create_app(settings=settings).state.settings is settings


def test_job_payload_hides_output_path(tmp_path: Path) -> None:
    app = create_app(
        settings=make_settings(tmp_path),
        map_client_factory=lambda settings: SolidColorMapClient(),
    )
    response = post_render(TestClient(app))
    assert response.status_code == 202
    payload = response.json()
    assert "output_path" not in payload
    assert payload["download_url"] is None


def test_failed_job_video_is_terminal_error(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path))
    job = RenderJob(
        id="failed",
        status="failed",
        output_path=tmp_path / "secret" / "route.mp4",
        estimated_map_requests=1,
        total_frames=1,
        error="Render failed.",
    )
    app.state.jobs.add(job)
    response = TestClient(app).get("/api/jobs/failed/video")
    assert response.status_code == 500
    assert response.json()["detail"] == "Render failed."


def test_failed_job_payload_hides_internal_error_details(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path))
    job = RenderJob(
        id="failed",
        status="failed",
        output_path=tmp_path / "secret" / "route.mp4",
        estimated_map_requests=1,
        total_frames=1,
        error="Render failed. Please try again.",
    )
    app.state.jobs.add(job)
    response = TestClient(app).get("/api/jobs/failed")
    assert response.status_code == 200
    assert "/app/" not in response.text
    assert "output_path" not in response.text
    assert "secret-google-key" not in response.text


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


def test_preview_hides_provider_exception_details(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    provider_url = "https://maps.example.com/?key=secret-google-key"

    class FailingMapClient:
        def fetch(self, *args, **kwargs) -> bytes:
            raise requests.HTTPError(provider_url)

    app = create_app(
        settings=make_settings(tmp_path),
        map_client_factory=lambda settings: FailingMapClient(),
    )
    with caplog.at_level(logging.ERROR):
        response = TestClient(app).post(
            "/api/preview",
            data={"duration_seconds": "5", "fps": "1"},
            files={"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")},
        )
    assert response.status_code == 500
    assert "secret-google-key" not in response.text
    assert "http" not in response.text
    assert "Preview could not be generated" in response.text

    assert any(
        record.message == "Preview render failed" and record.exc_info is not None
        for record in caplog.records
    )
    assert "Traceback" in caplog.text
    assert "Sensitive details redacted." in caplog.text
    assert "secret-google-key" not in caplog.text
    assert "maps.example.com" not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_render_job_hides_provider_exception_details(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    provider_url = "https://maps.example.com/?key=secret-google-key"

    class FailingMapClient:
        def fetch(self, *args, **kwargs) -> bytes:
            raise requests.HTTPError(provider_url)

    app = create_app(
        settings=make_settings(tmp_path),
        map_client_factory=lambda settings: FailingMapClient(),
    )
    with caplog.at_level(logging.ERROR):
        response = post_render(TestClient(app))
        status = TestClient(app).get(f"/api/jobs/{response.json()['id']}")

    assert response.status_code == 202
    assert status.status_code == 200
    assert status.json()["status"] == "failed"
    assert "secret-google-key" not in status.text
    assert "http" not in status.text
    assert status.json()["error"] == "Render failed. Please try again."

    assert any(
        record.message == "Render job failed"
        and record.exc_info is not None
        and getattr(record, "job_id", None) == response.json()["id"]
        for record in caplog.records
    )
    assert "Traceback" in caplog.text
    assert "Sensitive details redacted." in caplog.text
    assert "secret-google-key" not in caplog.text
    assert "maps.example.com" not in caplog.text
    assert str(tmp_path) not in caplog.text


def test_preview_frame_uses_single_map_request(tmp_path: Path) -> None:
    map_client = SolidColorMapClient()
    app = create_app(
        settings=make_settings(tmp_path), map_client_factory=lambda settings: map_client
    )
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


def test_render_rejects_invalid_trail_color(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path))
    response = post_render(TestClient(app), trail_color="not-a-color")
    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "Trail color must be a six-digit hex color such as #ff2f2f."
    )


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


def test_render_accepts_valid_recaptcha_in_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, float | bool]:
            return {"success": True, "score": 0.9}

    def fake_post(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    map_client = SolidColorMapClient()
    app = create_app(settings=settings, map_client_factory=lambda settings: map_client)
    client = TestClient(app)
    response = post_render(client, recaptcha_token="token")
    assert response.status_code == 202


def test_render_rejects_low_recaptcha_score_in_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, float | bool]:
            return {"success": True, "score": 0.4}

    def fake_post(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(requests, "post", fake_post)

    app = create_app(settings=settings)
    client = TestClient(app)
    response = post_render(client, recaptcha_token="token")
    assert response.status_code == 403
    assert "reCAPTCHA score is too low" in response.json()["detail"]


@pytest.mark.parametrize(
    "response",
    [
        pytest.param(requests.HTTPError("provider unavailable"), id="http-error"),
        pytest.param(ValueError("not json"), id="invalid-json"),
        pytest.param(["not", "a", "dict"], id="non-dict-json"),
        pytest.param({"success": True, "score": "not-a-number"}, id="nonnumeric-score"),
        pytest.param({"success": "true", "score": 0.9}, id="non-boolean-success"),
        pytest.param({"success": True, "score": "nan"}, id="nan-score"),
        pytest.param({"success": True, "score": "inf"}, id="infinite-score"),
        pytest.param({"success": True, "score": 1.1}, id="score-above-one"),
    ],
)
def test_render_rejects_malformed_recaptcha_provider_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: object,
) -> None:
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
        def raise_for_status(self) -> None:
            if isinstance(response, requests.HTTPError):
                raise response

        def json(self) -> object:
            if isinstance(response, ValueError):
                raise response
            return response

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: MockResponse())

    app = create_app(settings=settings)
    result = post_render(TestClient(app), recaptcha_token="token")
    assert result.status_code == 502
    assert (
        result.json()["detail"] == "reCAPTCHA verification is temporarily unavailable."
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_render_job_completes_with_mocked_maps(tmp_path: Path) -> None:
    map_client = SolidColorMapClient()
    app = create_app(
        settings=make_settings(tmp_path), map_client_factory=lambda settings: map_client
    )
    client = TestClient(app)

    response = post_render(client)

    assert response.status_code == 202
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
