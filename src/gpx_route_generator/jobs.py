from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


@dataclass
class RenderJob:
    id: str
    status: str
    output_path: Path
    estimated_map_requests: int
    total_frames: int
    progress_frames: int = 0
    actual_map_requests: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def progress(self) -> float:
        if self.total_frames <= 0:
            return 0.0
        return min(1.0, self.progress_frames / self.total_frames)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["output_path"] = str(self.output_path)
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        data["progress"] = self.progress
        data["download_url"] = f"/api/jobs/{self.id}/video" if self.status == "completed" else None
        return data


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, RenderJob] = {}
        self._lock = Lock()

    def add(self, job: RenderJob) -> None:
        with self._lock:
            self._jobs[job.id] = job

    def get(self, job_id: str) -> RenderJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes: object) -> RenderJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for key, value in changes.items():
                setattr(job, key, value)
            job.updated_at = datetime.now(timezone.utc)
            return job

