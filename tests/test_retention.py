from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from gpx_route_generator.jobs import JobStore, RenderJob
from gpx_route_generator.retention import JobRetention


def make_job(root: Path, job_id: str, status: str, age_hours: int = 0) -> RenderJob:
    path = root / job_id / "route.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"video")
    created = datetime.now(UTC) - timedelta(hours=age_hours)
    return RenderJob(
        id=job_id,
        status=status,
        output_path=path,
        estimated_map_requests=1,
        total_frames=1,
        created_at=created,
        updated_at=created,
    )


def test_cleanup_removes_expired_terminal_jobs_but_preserves_active(tmp_path: Path) -> None:
    store = JobStore()
    expired = make_job(tmp_path, "expired", "completed", age_hours=25)
    active = make_job(tmp_path, "active", "running", age_hours=25)
    store.add(expired)
    store.add(active)

    JobRetention(tmp_path, retention_hours=24, max_jobs=100, max_bytes=1_000).cleanup(store)

    assert store.get("expired") is None
    assert not expired.output_path.parent.exists()
    assert store.get("active") is not None
    assert active.output_path.exists()


def test_cleanup_removes_orphan_and_partial_files(tmp_path: Path) -> None:
    store = JobStore()
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    (orphan / "route.mp4").write_bytes(b"orphan")
    partial = tmp_path / ".orphan.partial.mp4"
    partial.write_bytes(b"partial")

    JobRetention(tmp_path, retention_hours=24, max_jobs=100, max_bytes=1_000).cleanup(store)

    assert not orphan.exists()
    assert not partial.exists()


def test_cleanup_keeps_newest_terminal_jobs_under_count_limit(tmp_path: Path) -> None:
    store = JobStore()
    old = make_job(tmp_path, "old", "completed", age_hours=2)
    new = make_job(tmp_path, "new", "failed", age_hours=1)
    store.add(old)
    store.add(new)

    JobRetention(tmp_path, retention_hours=24, max_jobs=1, max_bytes=1_000).cleanup(store)

    assert store.get("old") is None
    assert store.get("new") is not None


def test_cleanup_unlinks_symlink_without_deleting_target_job(tmp_path: Path) -> None:
    store = JobStore()
    active = make_job(tmp_path, "active", "running")
    store.add(active)
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    (orphan / "active-link").symlink_to(active.output_path.parent, target_is_directory=True)

    JobRetention(tmp_path, retention_hours=24, max_jobs=100, max_bytes=1_000).cleanup(store)

    assert active.output_path.read_bytes() == b"video"
    assert not orphan.exists()


def test_cleanup_reports_storage_and_rejects_invalid_paths(tmp_path: Path) -> None:
    store = JobStore()
    job = make_job(tmp_path, "job", "completed")
    store.add(job)
    retention = JobRetention(tmp_path, retention_hours=24, max_jobs=100, max_bytes=5)

    assert retention.storage_bytes() == 5
    assert retention.has_capacity(store) is False
    outside = tmp_path.parent / "outside.mp4"
    outside.write_bytes(b"outside")
    assert retention.remove_path_safely(outside) is False
    assert outside.exists()
