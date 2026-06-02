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
    environment: str = "local"
    recaptcha_site_key: str | None = None
    recaptcha_secret_key: str | None = None
    ffmpeg_path: str = "ffmpeg"

    @property
    def recaptcha_enabled(self) -> bool:
        return (
            self.environment.lower() == "production"
            and bool(self.recaptcha_site_key)
            and bool(self.recaptcha_secret_key)
        )


def load_settings() -> Settings:
    load_dotenv()
    project_root = Path.cwd()
    return Settings(
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
        google_maps_signature_secret=os.getenv("GOOGLE_MAPS_SIGNATURE_SECRET"),
        environment=os.getenv("APP_ENV", "local"),
        recaptcha_site_key=os.getenv("RECAPTCHA_SITE_KEY"),
        recaptcha_secret_key=os.getenv("RECAPTCHA_SECRET_KEY"),
        jobs_dir=project_root / "data" / "jobs",
        ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
    )
