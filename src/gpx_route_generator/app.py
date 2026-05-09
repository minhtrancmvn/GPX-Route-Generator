from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import Settings, load_settings
from .gpx import parse_gpx_bytes
from .jobs import JobStore, RenderJob
from .maps import GoogleStaticMapClient
from .models import OutputFormat, RenderOptions, validate_render_options
from .renderer import render_route_video

BUDGET_CONFIRMATION_THRESHOLD = 750

MapClientFactory = Callable[[Settings], GoogleStaticMapClient]


def default_map_client_factory(settings: Settings) -> GoogleStaticMapClient:
    if not settings.google_maps_api_key:
        raise ValueError("Set GOOGLE_MAPS_API_KEY in .env before rendering.")
    return GoogleStaticMapClient(
        api_key=settings.google_maps_api_key,
        signature_secret=settings.google_maps_signature_secret,
    )


def create_app(
    settings: Settings | None = None,
    map_client_factory: MapClientFactory = default_map_client_factory,
) -> FastAPI:
    app = FastAPI(title="GPX Route Generator")
    package_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(package_dir / "templates"))
    app.mount("/static", StaticFiles(directory=str(package_dir / "static")), name="static")
    app.state.settings = settings or load_settings()
    app.state.jobs = JobStore()
    app.state.map_client_factory = map_client_factory

    @app.get("/")
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {})

    @app.post("/api/render")
    async def start_render(
        background_tasks: BackgroundTasks,
        gpx_file: UploadFile = File(...),
        output_format: str = Form("landscape"),
        duration_seconds: float = Form(10),
        fps: int = Form(24),
        zoom: int = Form(18),
        map_type: str = Form("roadmap"),
        trail_color: str = Form("#ff2f2f"),
        trail_width: int = Form(6),
        arrow_size: int = Form(54),
        show_progress_bar: bool = Form(True),
        show_time: bool = Form(True),
        show_distance: bool = Form(True),
        show_speed: bool = Form(True),
        show_elevation: bool = Form(True),
        confirm_over_budget: bool = Form(False),
    ):
        if not app.state.settings.google_maps_api_key:
            raise HTTPException(status_code=400, detail="Set GOOGLE_MAPS_API_KEY in .env before rendering.")

        try:
            parsed_format = OutputFormat(output_format)
            options = RenderOptions(
                output_format=parsed_format,
                duration_seconds=duration_seconds,
                fps=fps,
                zoom=zoom,
                map_type=map_type,
                trail_color=trail_color,
                trail_width=trail_width,
                arrow_size=arrow_size,
                show_progress_bar=show_progress_bar,
                show_time=show_time,
                show_distance=show_distance,
                show_speed=show_speed,
                show_elevation=show_elevation,
            )
            validate_render_options(options)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if options.estimated_map_requests > BUDGET_CONFIRMATION_THRESHOLD and not confirm_over_budget:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This render is estimated to request {options.estimated_map_requests} Google maps. "
                    f"Confirm renders above {BUDGET_CONFIRMATION_THRESHOLD} requests to continue."
                ),
            )

        try:
            points = parse_gpx_bytes(await gpx_file.read())
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
        return job.to_dict()

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
        if job.status != "completed" or not job.output_path.exists():
            raise HTTPException(status_code=409, detail="Render video is not ready yet.")
        return FileResponse(job.output_path, filename=f"gpx-route-{job_id}.mp4", media_type="video/mp4")

    return app


def run_render_job(app: FastAPI, job_id: str, points, options: RenderOptions) -> None:
    settings: Settings = app.state.settings
    app.state.jobs.update(job_id, status="running")
    try:
        map_client = app.state.map_client_factory(settings)

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
            actual_map_requests=options.estimated_map_requests,
        )
    except Exception as exc:
        app.state.jobs.update(job_id, status="failed", error=str(exc))


app = create_app()
