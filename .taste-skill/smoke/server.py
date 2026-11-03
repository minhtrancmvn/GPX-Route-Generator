from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
import uvicorn

# Ensure canonical src is first on sys.path
CANONICAL_SRC = "/Users/coffeemug/Programming/GPX Route Generator/src"
if CANONICAL_SRC not in sys.path:
    sys.path.insert(0, CANONICAL_SRC)

from gpx_route_generator.config import Settings
from gpx_route_generator.maps import SolidColorMapClient
from gpx_route_generator.app import create_app

tmp_jobs_dir = Path(tempfile.mkdtemp(prefix="gpx_smoke_jobs_"))
print(f"Temporary jobs directory: {tmp_jobs_dir}", flush=True)

settings = Settings(
    google_maps_api_key="smoke-test-dummy-key",
    google_maps_signature_secret=None,
    jobs_dir=tmp_jobs_dir,
    environment="local",
    recaptcha_site_key=None,
    recaptcha_secret_key=None,
    ffmpeg_path="/opt/homebrew/bin/ffmpeg",
    preview_requests_per_minute=300,
    render_requests_per_minute=60,
    max_active_previews=10,
)

app = create_app(
    settings=settings,
    map_client_factory=lambda _s: SolidColorMapClient(),
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="info")
