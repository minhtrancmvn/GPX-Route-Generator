from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock

from .jobs import JobStore, RenderJob


class JobRetention:
    def __init__(
        self,
        jobs_dir: Path,
        *,
        retention_hours: int,
        max_jobs: int,
        max_bytes: int,
    ) -> None:
        if retention_hours <= 0:
            raise ValueError("JOB_RETENTION_HOURS must be greater than zero.")
        if max_jobs < 1:
            raise ValueError("MAX_RETAINED_JOBS must be at least one.")
        if max_bytes <= 0:
            raise ValueError("MAX_JOB_STORAGE_BYTES must be greater than zero.")
        self.jobs_dir = jobs_dir.resolve()
        self.retention = timedelta(hours=retention_hours)
        self.max_jobs = max_jobs
        self.max_bytes = max_bytes
        self._lock = RLock()

    def _within_jobs_dir(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.jobs_dir)
        except ValueError:
            return False
        return True

    def remove_path_safely(self, path: Path) -> bool:
        absolute = path.absolute()
        if absolute == self.jobs_dir or self.jobs_dir not in absolute.parents:
            return False
        if path.is_symlink():
            path.unlink(missing_ok=True)
            return True
        resolved = path.resolve()
        if not self._within_jobs_dir(resolved):
            return False
        if resolved.is_dir():
            for child in resolved.iterdir():
                self.remove_path_safely(child)
            try:
                resolved.rmdir()
            except OSError:
                pass
        else:
            resolved.unlink(missing_ok=True)
        return True

    def storage_bytes(self) -> int:
        if not self.jobs_dir.exists():
            return 0
        return sum(path.stat().st_size for path in self.jobs_dir.rglob("*") if path.is_file())

    def has_capacity(self, store: JobStore) -> bool:
        with self._lock:
            self.cleanup(store)
            return self.storage_bytes() < self.max_bytes

    def cleanup(self, store: JobStore) -> None:
        with self._lock:
            now = datetime.now(UTC)
            jobs = store.list_jobs()
            terminal = [job for job in jobs if job.status in {"completed", "failed"}]
            for job in terminal:
                if now - job.updated_at > self.retention:
                    self._remove_job(store, job)
            terminal = sorted(
                [job for job in store.list_jobs() if job.status in {"completed", "failed"}],
                key=lambda job: job.updated_at,
            )
            for job in terminal[: max(0, len(terminal) - self.max_jobs)]:
                self._remove_job(store, job)
            if self.jobs_dir.exists():
                for partial in self.jobs_dir.rglob("*.partial.mp4"):
                    self.remove_path_safely(partial)
                known = {job.id for job in store.list_jobs()}
                for child in self.jobs_dir.iterdir():
                    if child.is_dir() and child.name not in known:
                        self.remove_path_safely(child)

    def _remove_job(self, store: JobStore, job: RenderJob) -> None:
        if not self.remove_path_safely(job.output_path.parent):
            return
        store.remove_terminal(job.id)
