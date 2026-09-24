from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
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
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def progress(self) -> float:
        if self.total_frames <= 0:
            return 0.0
        return min(1.0, self.progress_frames / self.total_frames)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "estimated_map_requests": self.estimated_map_requests,
            "total_frames": self.total_frames,
            "progress_frames": self.progress_frames,
            "actual_map_requests": self.actual_map_requests,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "download_url": f"/api/jobs/{self.id}/video"
            if self.status == "completed"
            else None,
        }


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
            job.updated_at = datetime.now(UTC)
            return job
