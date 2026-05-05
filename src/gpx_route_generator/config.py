from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    google_maps_api_key: str | None
    google_maps_signature_secret: str | None
    jobs_dir: Path
    ffmpeg_path: str = "ffmpeg"


def load_settings() -> Settings:
    load_dotenv()
    project_root = Path.cwd()
    return Settings(
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
        google_maps_signature_secret=os.getenv("GOOGLE_MAPS_SIGNATURE_SECRET"),
        jobs_dir=project_root / "data" / "jobs",
        ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
    )

