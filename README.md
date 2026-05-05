# GPX Route Generator

A local FastAPI app that turns a GPX track into a short MP4 route animation using Google Maps Static API backgrounds, a progressive trail, a smoothly-following camera, HUD overlays, and a rotating arrow avatar placeholder.

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

`ffmpeg` must be available on `PATH`.

## Run

```bash
uvicorn gpx_route_generator.app:app --reload
```

Open http://127.0.0.1:8000, upload a GPX file, choose landscape or portrait output, set a 5-15 second duration, and render.

## Notes

- V1 is local-only and stores render outputs under `data/jobs/`.
- Each rendered frame requests a Google Static Maps image. The UI estimates request count before rendering.
- The renderer automatically chooses a dynamic local zoom around the moving position, keeping nearby route context visible without falling back to a whole-country overview for long drives.
- The driving avatar can be swapped in later; V1 uses a Pillow-drawn arrow that rotates to route bearing.
