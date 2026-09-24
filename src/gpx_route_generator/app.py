from __future__ import annotations

import logging
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import requests
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings, load_settings, validate_settings
from .gpx import parse_gpx_bytes
from .jobs import JobStore, RenderJob
from .maps import GoogleStaticMapClient, StaticMapClient
from .models import (
    AVAILABLE_AVATARS,
    OutputFormat,
    RenderOptions,
    validate_render_options,
)
from .preview import render_preview_frame_2d
from .renderer import make_arrow, render_route_video

RECAPTCHA_MIN_SCORE = 0.5
RECAPTCHA_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"
logger = logging.getLogger(__name__)

MapClientFactory = Callable[[Settings], StaticMapClient]


class UploadTooLargeError(ValueError):
    pass


async def _read_upload(upload: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(64 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(f"GPX upload exceeds the {max_bytes} byte limit.")
        chunks.append(chunk)
    return b"".join(chunks)


def default_map_client_factory(settings: Settings) -> StaticMapClient:
    if not settings.google_maps_api_key:
        raise ValueError("Set GOOGLE_MAPS_API_KEY in .env before rendering.")
    return GoogleStaticMapClient(
        api_key=settings.google_maps_api_key,
        signature_secret=settings.google_maps_signature_secret,
    )


def _build_options(
    *,
    output_format: str,
    duration_seconds: float,
    fps: int,
    zoom: int,
    map_type: str,
    trail_color: str,
    trail_width: int,
    arrow_size: int,
    avatar_id: str,
    show_progress_bar: bool,
    show_distance: bool,
    show_speed: bool,
    show_elevation: bool,
) -> RenderOptions:
    options = RenderOptions(
        output_format=OutputFormat(output_format),
        duration_seconds=duration_seconds,
        fps=fps,
        zoom=zoom,
        map_type=map_type,
        trail_color=trail_color,
        trail_width=trail_width,
        arrow_size=arrow_size,
        avatar_id=avatar_id,
        show_progress_bar=show_progress_bar,
        show_distance=show_distance,
        show_speed=show_speed,
        show_elevation=show_elevation,
    )
    validate_render_options(options)
    return options


def create_app(
    settings: Settings | None = None,
    map_client_factory: MapClientFactory = default_map_client_factory,
) -> FastAPI:
    app = FastAPI(title="GPX Route Generator")
    package_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(package_dir / "templates"))
    app.mount(
        "/static", StaticFiles(directory=str(package_dir / "static")), name="static"
    )
    app.state.settings = settings or load_settings()
    validate_settings(app.state.settings)
    app.state.jobs = JobStore()
    app.state.map_client_factory = map_client_factory

    @app.get("/")
    async def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "avatars": AVAILABLE_AVATARS,
                "recaptcha_enabled": app.state.settings.recaptcha_enabled,
                "recaptcha_site_key": app.state.settings.recaptcha_site_key,
            },
        )

    @app.get("/api/avatars/{avatar_id}/preview")
    async def avatar_preview(avatar_id: str, size: int = 54):
        try:
            options = RenderOptions(avatar_id=avatar_id, arrow_size=size)
            validate_render_options(options)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        image = make_arrow(options.arrow_size, options.avatar_id)
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return Response(content=buffer.getvalue(), media_type="image/png")

    @app.get("/api/config")
    async def public_config():
        return {
            "has_google_maps_key": bool(app.state.settings.google_maps_api_key),
            "avatars": AVAILABLE_AVATARS,
            "recaptcha_enabled": app.state.settings.recaptcha_enabled,
            "recaptcha_site_key": app.state.settings.recaptcha_site_key
            if app.state.settings.recaptcha_enabled
            else None,
        }

    def verify_recaptcha(token: str | None, remote_ip: str | None) -> None:
        settings: Settings = app.state.settings
        if not settings.recaptcha_enabled:
            return
        if not token:
            raise HTTPException(
                status_code=400, detail="reCAPTCHA verification is required."
            )

        try:
            response = requests.post(
                RECAPTCHA_VERIFY_URL,
                data={
                    "secret": settings.recaptcha_secret_key,
                    "response": token,
                    "remoteip": remote_ip,
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("reCAPTCHA response must be a JSON object.")
            success = payload["success"]
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            raise HTTPException(
                status_code=502,
                detail="reCAPTCHA verification is temporarily unavailable.",
            ) from exc

        if not success:
            raise HTTPException(
                status_code=400,
                detail="reCAPTCHA verification failed. Please try again.",
            )
        try:
            score = float(payload["score"])
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(
                status_code=502,
                detail="reCAPTCHA verification is temporarily unavailable.",
            ) from exc
        if score < RECAPTCHA_MIN_SCORE:
            raise HTTPException(
                status_code=403,
                detail="reCAPTCHA score is too low. Rendering is blocked.",
            )

    @app.post("/api/gpx/parse")
    async def parse_gpx_endpoint(gpx_file: UploadFile = File(...)):
        try:
            data = await _read_upload(
                gpx_file, max_bytes=app.state.settings.max_upload_bytes
            )
            points = parse_gpx_bytes(
                data, max_points=app.state.settings.max_route_points
            )
        except UploadTooLargeError as exc:
            raise HTTPException(
                status_code=413, detail="GPX upload is too large."
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "points": [
                {
                    "lat": p.lat,
                    "lon": p.lon,
                    "elevation": p.elevation,
                    "time": p.time.isoformat() if p.time else None,
                }
                for p in points
            ],
        }

    @app.post("/api/preview")
    async def preview_frame(
        gpx_file: UploadFile = File(...),
        output_format: str = Form("landscape"),
        duration_seconds: float = Form(10),
        fps: int = Form(24),
        zoom: int = Form(14),
        map_type: str = Form("roadmap"),
        trail_color: str = Form("#ff2f2f"),
        trail_width: int = Form(6),
        arrow_size: int = Form(54),
        avatar_id: str = Form("default"),
        show_progress_bar: bool = Form(True),
        show_distance: bool = Form(True),
        show_speed: bool = Form(True),
        show_elevation: bool = Form(True),
    ):
        if not app.state.settings.google_maps_api_key:
            raise HTTPException(
                status_code=400,
                detail="Set GOOGLE_MAPS_API_KEY in .env before preview.",
            )
        try:
            options = _build_options(
                output_format=output_format,
                duration_seconds=duration_seconds,
                fps=fps,
                zoom=zoom,
                map_type=map_type,
                trail_color=trail_color,
                trail_width=trail_width,
                arrow_size=arrow_size,
                avatar_id=avatar_id,
                show_progress_bar=show_progress_bar,
                show_distance=show_distance,
                show_speed=show_speed,
                show_elevation=show_elevation,
            )
            data = await _read_upload(
                gpx_file, max_bytes=app.state.settings.max_upload_bytes
            )
            points = parse_gpx_bytes(
                data, max_points=app.state.settings.max_route_points
            )
            map_client = app.state.map_client_factory(app.state.settings)
            image = render_preview_frame_2d(points, options, map_client)
        except UploadTooLargeError as exc:
            raise HTTPException(
                status_code=413, detail="GPX upload is too large."
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            logger.error("Preview render failed")
            raise HTTPException(
                status_code=500,
                detail="Preview could not be generated. Please try again.",
            ) from None

        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return Response(content=buffer.getvalue(), media_type="image/png")

    @app.post("/api/render")
    async def start_render(
        request: Request,
        background_tasks: BackgroundTasks,
        gpx_file: UploadFile = File(...),
        output_format: str = Form("landscape"),
        duration_seconds: float = Form(10),
        fps: int = Form(24),
        zoom: int = Form(14),
        map_type: str = Form("roadmap"),
        trail_color: str = Form("#ff2f2f"),
        trail_width: int = Form(6),
        arrow_size: int = Form(54),
        avatar_id: str = Form("default"),
        show_progress_bar: bool = Form(True),
        show_distance: bool = Form(True),
        show_speed: bool = Form(True),
        show_elevation: bool = Form(True),
        recaptcha_token: str | None = Form(None),
    ):
        if not app.state.settings.google_maps_api_key:
            raise HTTPException(
                status_code=400,
                detail="Set GOOGLE_MAPS_API_KEY in .env before rendering.",
            )
        verify_recaptcha(
            recaptcha_token, request.client.host if request.client else None
        )
        try:
            options = _build_options(
                output_format=output_format,
                duration_seconds=duration_seconds,
                fps=fps,
                zoom=zoom,
                map_type=map_type,
                trail_color=trail_color,
                trail_width=trail_width,
                arrow_size=arrow_size,
                avatar_id=avatar_id,
                show_progress_bar=show_progress_bar,
                show_distance=show_distance,
                show_speed=show_speed,
                show_elevation=show_elevation,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            data = await _read_upload(
                gpx_file, max_bytes=app.state.settings.max_upload_bytes
            )
            points = parse_gpx_bytes(
                data, max_points=app.state.settings.max_route_points
            )
        except UploadTooLargeError as exc:
            raise HTTPException(
                status_code=413, detail="GPX upload is too large."
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        job_id = uuid4().hex
        output_path = app.state.settings.jobs_dir / job_id / "route.mp4"
        job = RenderJob(
            id=job_id,
            status="queued",
            output_path=output_path,
            estimated_map_requests=options.estimated_map_requests,
            total_frames=options.frame_count,
        )
        app.state.jobs.add(job)
        background_tasks.add_task(run_render_job, app, job_id, points, options)
        return JSONResponse(status_code=202, content=job.to_dict())

    @app.get("/api/jobs/{job_id}")
    async def job_status(job_id: str):
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Render job not found.")
        return job.to_dict()

    @app.get("/api/jobs/{job_id}/video")
    async def job_video(job_id: str):
        job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Render job not found.")
        if job.status == "failed":
            raise HTTPException(status_code=500, detail=job.error or "Render failed.")
        if job.status != "completed" or not job.output_path.exists():
            raise HTTPException(
                status_code=409, detail="Render video is not ready yet."
            )
        return FileResponse(
            job.output_path, filename=f"gpx-route-{job_id}.mp4", media_type="video/mp4"
        )

    return app


def run_render_job(app: FastAPI, job_id: str, points, options: RenderOptions) -> None:
    settings: Settings = app.state.settings
    app.state.jobs.update(job_id, status="running")
    try:

        def update_progress(done: int, total: int, map_requests: int) -> None:
            app.state.jobs.update(
                job_id,
                progress_frames=done,
                total_frames=total,
                actual_map_requests=map_requests,
            )

        job = app.state.jobs.get(job_id)
        if job is None:
            return
        map_client = app.state.map_client_factory(settings)
        render_route_video(
            points=points,
            options=options,
            output_path=job.output_path,
            map_client=map_client,
            ffmpeg_path=settings.ffmpeg_path,
            progress_callback=update_progress,
        )
        app.state.jobs.update(
            job_id,
            status="completed",
            progress_frames=options.frame_count,
        )
    except Exception:
        logger.error("Render job failed", extra={"job_id": job_id})
        app.state.jobs.update(
            job_id, status="failed", error="Render failed. Please try again."
        )


app = create_app()
