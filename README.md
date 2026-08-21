# GPX Route Generator

A local FastAPI app that turns a GPX track into a short MP4 route animation using Google Maps Static API backgrounds, a progressive trail, a smoothly-following camera, HUD overlays, and a rotating motorcycle avatar.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Add your Google Maps Static API key to `.env`:

```bash
GOOGLE_MAPS_API_KEY=...
```

Optional production-only reCAPTCHA v3 settings for the `Render MP4` button:

```bash
APP_ENV=local
RECAPTCHA_SITE_KEY=...
RECAPTCHA_SECRET_KEY=...
```

Keep `APP_ENV=local` for development so reCAPTCHA stays hidden locally. Set `APP_ENV=production` on your deployed server to require a reCAPTCHA token before `/api/render` starts a job.

`ffmpeg` is required for MP4 renders.

## App commands

Start the app (uses `--reload-dir src` so the reloader ignores `.venv`):

```bash
./scripts/dev.sh
```

The script wraps the underlying command and accepts `HOST`/`PORT` overrides:

```bash
PORT=9000 ./scripts/dev.sh
```

Equivalent manual command:

```bash
PYTHONPATH=src uvicorn gpx_route_generator.app:app --reload --reload-dir src
```

The renderer fetches a small set of reusable Google Static Map source images before composing frames. Tune `FRAME_WORKERS` to bound both source-image prefetching and concurrent frame composition:

```bash
FRAME_WORKERS=6 ./scripts/dev.sh
```

Stop a foreground server with `Ctrl+C`.

Stop a server already running on port 8000:

```bash
lsof -ti tcp:8000 | xargs kill
```

Restart the app:

```bash
lsof -ti tcp:8000 | xargs kill
./scripts/dev.sh
```

Open http://127.0.0.1:8000, upload a GPX file, choose landscape or portrait output, set a 5-30 second duration, and render.

## Docker

Build and run locally with Docker Compose:

```bash
cp .env.example .env
# Add GOOGLE_MAPS_API_KEY to .env first.
docker compose up --build
```

Open http://127.0.0.1:8000. Render outputs are persisted to `./data/jobs` via the bind mount in `docker-compose.yml`.

Tune concurrent frame generation by overriding `FRAME_WORKERS`:

```bash
FRAME_WORKERS=6 docker compose up --build
```

Build and run without Compose:

```bash
docker build -t gpx-route-generator .
docker run --rm -p 8000:8000 --env-file .env -v "$PWD/data:/app/data" gpx-route-generator
```

## AWS Lightsail with Docker

1. Create an Ubuntu Lightsail instance, attach a static IP, and allow inbound HTTP/HTTPS in the Lightsail firewall.
2. Install Docker and the Compose plugin on the instance.
3. Clone this repository onto the instance.
4. Create `.env` from `.env.example` and set `GOOGLE_MAPS_API_KEY`. If you want to protect renders, also set `APP_ENV=production`, `RECAPTCHA_SITE_KEY`, and `RECAPTCHA_SECRET_KEY`.
5. Start the app:

```bash
docker compose up -d --build
```

For production, put Nginx or Caddy in front of the container for HTTPS and proxy traffic to `127.0.0.1:8000`. Keep `./data` on the Lightsail disk, or move completed MP4s to S3 later if you need durable external storage.

## Notes

- V1 is local-only and stores render outputs under `data/jobs/`.
- Each render automatically plans and temporarily caches up to 12 high-resolution Google Static Map images in memory. Every video frame crops from one cached source image, reducing map requests from one per frame to a small bounded set.
- Output stays north-up 2D because Google Maps Static API does not provide pitched or 3D camera images.
- The renderer targets zoom level 14, matching the horizontal scale in supplied reference. Very long routes widen only enough to remain within 12 source images.
- The renderer automatically follows the moving position while keeping nearby route context visible.
- The driving avatar is a top-down motorcycle icon (`mt15.png`) that rotates to match the route bearing.
