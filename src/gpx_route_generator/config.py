from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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
    max_upload_bytes: int = 5 * 1024 * 1024
    max_route_points: int = 50_000
    allow_unprotected_rendering: bool = False
    max_active_renders: int = 1
    max_queued_renders: int = 2

    @property
    def recaptcha_enabled(self) -> bool:
        return (
            self.environment.lower() == "production"
            and bool(self.recaptcha_site_key)
            and bool(self.recaptcha_secret_key)
        )


def _get_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer greater than zero.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _get_nonnegative_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer zero or greater.") from exc
    if value < 0:
        raise ValueError(f"{name} must be zero or greater.")
    return value


def validate_settings(settings: Settings) -> None:
    if settings.max_upload_bytes <= 0:
        raise ValueError("MAX_UPLOAD_BYTES must be greater than zero.")
    if settings.max_route_points < 2:
        raise ValueError("MAX_ROUTE_POINTS must be at least two.")
    if settings.max_active_renders < 1:
        raise ValueError("MAX_ACTIVE_RENDERS must be at least one.")
    if settings.max_queued_renders < 0:
        raise ValueError("MAX_QUEUED_RENDERS must be zero or greater.")
    if settings.environment.lower() == "production":
        recaptcha_ready = bool(settings.recaptcha_site_key and settings.recaptcha_secret_key)
        if not recaptcha_ready and not settings.allow_unprotected_rendering:
            raise ValueError(
                "Production requires RECAPTCHA_SITE_KEY and RECAPTCHA_SECRET_KEY "
                "or explicit ALLOW_UNPROTECTED_RENDERING=true."
            )


def load_settings() -> Settings:
    load_dotenv()
    project_root = Path.cwd()
    settings = Settings(
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY"),
        google_maps_signature_secret=os.getenv("GOOGLE_MAPS_SIGNATURE_SECRET"),
        environment=os.getenv("APP_ENV", "local"),
        recaptcha_site_key=os.getenv("RECAPTCHA_SITE_KEY"),
        recaptcha_secret_key=os.getenv("RECAPTCHA_SECRET_KEY"),
        jobs_dir=project_root / "data" / "jobs",
        ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
        max_upload_bytes=_get_positive_int("MAX_UPLOAD_BYTES", 5 * 1024 * 1024),
        max_route_points=_get_positive_int("MAX_ROUTE_POINTS", 50_000),
        allow_unprotected_rendering=os.getenv("ALLOW_UNPROTECTED_RENDERING", "").lower() in {"1", "true", "yes", "on"},
        max_active_renders=_get_positive_int("MAX_ACTIVE_RENDERS", 1),
        max_queued_renders=_get_nonnegative_int("MAX_QUEUED_RENDERS", 2),
    )
    validate_settings(settings)
    return settings
