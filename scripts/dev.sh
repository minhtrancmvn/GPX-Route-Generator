#!/usr/bin/env bash
# Start the GPX Route Generator dev server.
#
# Watches only the application source (src/) for changes so the reloader
# ignores the virtualenv. Without this, Playwright touching files under
# .venv/ during 3D renders triggers spurious server restarts.
set -euo pipefail

cd "$(dirname "$0")/.."

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

PYTHONPATH=src exec uvicorn gpx_route_generator.app:app \
  --reload \
  --reload-dir src \
  --host "$HOST" \
  --port "$PORT"
