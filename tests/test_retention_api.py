from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gpx_route_generator.app import create_app
from gpx_route_generator.config import load_settings, validate_settings
from gpx_route_generator.jobs import RenderJob
from gpx_route_generator.maps import SolidColorMapClient

from test_api import make_settings, post_render


def test_settings_reject_invalid_retention_limits(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    with pytest.raises(ValueError, match="JOB_RETENTION_HOURS"):
        validate_settings(replace(settings, job_retention_hours=0))
    with pytest.raises(ValueError, match="MAX_RETAINED_JOBS"):
        validate_settings(replace(settings, max_retained_jobs=0))
    with pytest.raises(ValueError, match="MAX_JOB_STORAGE_BYTES"):
        validate_settings(replace(settings, max_job_storage_bytes=0))


def test_load_settings_reads_retention_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JOB_RETENTION_HOURS", "12")
    monkeypatch.setenv("MAX_RETAINED_JOBS", "20")
    monkeypatch.setenv("MAX_JOB_STORAGE_BYTES", "4096")

    settings = load_settings()

    assert settings.job_retention_hours == 12
    assert settings.max_retained_jobs == 20
    assert settings.max_job_storage_bytes == 4096


def test_startup_cleanup_removes_orphans_and_partial_files(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "jobs"
    orphan = jobs_dir / "stale"
    orphan.mkdir(parents=True)
    (orphan / "route.mp4").write_bytes(b"orphan")
    partial = jobs_dir / ".stale.partial.mp4"
    partial.write_bytes(b"partial")
    app = create_app(settings=make_settings(tmp_path))

    assert app.state.jobs.list_jobs() == []
    assert not orphan.exists()
    assert not partial.exists()


def test_render_returns_503_when_storage_budget_is_exhausted(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), max_job_storage_bytes=5)
    app = create_app(
        settings=settings,
        map_client_factory=lambda _settings: SolidColorMapClient(),
    )
    output_path = settings.jobs_dir / "retained" / "route.mp4"
    output_path.parent.mkdir(parents=True)
    output_path.write_bytes(b"video")
    app.state.jobs.add(
        RenderJob(
            id="retained",
            status="completed",
            output_path=output_path,
            estimated_map_requests=1,
            total_frames=1,
        )
    )
    client = TestClient(app)

    response = post_render(client)

    assert response.status_code == 503
    assert response.json()["detail"] == "Render storage is full. Please try again later."


def test_cleanup_preserves_queued_jobs_during_render_acceptance(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    app = create_app(
        settings=settings,
        map_client_factory=lambda _settings: SolidColorMapClient(),
    )
    queued = RenderJob(
        id="queued",
        status="queued",
        output_path=settings.jobs_dir / "queued" / "route.mp4",
        estimated_map_requests=1,
        total_frames=1,
        created_at=datetime.now(UTC) - timedelta(days=30),
        updated_at=datetime.now(UTC) - timedelta(days=30),
    )
    app.state.jobs.add(queued)

    app.state.retention.cleanup(app.state.jobs)

    assert app.state.jobs.get("queued") is not None
