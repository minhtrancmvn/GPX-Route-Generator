# Public Safety Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound GPX inputs, remove sensitive error leakage, fail closed for incomplete production protection, correct asynchronous API contracts, and close the public Docker port.

**Architecture:** Keep the current FastAPI shape. Add bounded upload reading at the API boundary, route-point validation in the GPX parser, safe public error messages with server-side logging, and explicit production settings validation. Preserve process-local jobs and rendering architecture; queueing, FFmpeg lifecycle, and algorithmic optimization remain later slices.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic-independent dataclasses, `gpxpy`, `requests`, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-24-public-safety-hardening-design.md`

## Global Constraints

- Maximum upload size defaults to 5 MiB and is configurable through `MAX_UPLOAD_BYTES`.
- Maximum route points defaults to 50,000 and is configurable through `MAX_ROUTE_POINTS`.
- Uploads above the byte budget return HTTP `413`.
- Invalid route content returns HTTP `422`.
- Production startup requires both reCAPTCHA keys unless `ALLOW_UNPROTECTED_RENDERING=true`.
- Local and non-production environments preserve unprotected development behavior.
- Public responses must not include Google Maps API keys, filesystem paths, or raw exception text.
- Render submission returns HTTP `202` because rendering is asynchronous.
- Queued or running video requests return HTTP `409`; failed jobs return a terminal failure status.
- Existing user changes in `CLAUDE.md`, `GPX Route Generator.code-workspace`, and review artifacts remain untouched.
- GitNexus impact analysis is unavailable because this repository is not indexed; record that limitation before editing symbols and use direct source/test inspection.
- Do not commit directly to `main`; work stays on `safety/public-hardening`.

## Review Focus

- A chunked upload crosses the size limit after several successful reads; the server must stop reading and return `413` without parsing it.
- A route has exactly `MAX_ROUTE_POINTS` points versus one more; the boundary must accept the former and reject the latter.
- A GPX point has `NaN`, infinity, latitude `90.1`, or longitude `180.1`; the API must reject it with `422` before geometry work.
- Google Maps returns an HTTP error whose exception contains the signed request URL; the response must not contain the API key or URL.
- A render fails with `/app/data/jobs/...` in its exception; polling must expose only a stable public message and no filesystem path.

---

### Task 1: Add bounded GPX input and route validation

**Files:**
- Modify: `src/gpx_route_generator/config.py:10-39` — add input-limit settings and strict production configuration validation.
- Modify: `src/gpx_route_generator/gpx.py:12-38` — enforce byte/point/coordinate limits while parsing.
- Modify: `src/gpx_route_generator/app.py:14-20,145-160,163-208,210-268` — add shared bounded upload reader and map limit errors to HTTP statuses.
- Modify: `tests/test_gpx.py:21-38` — add parser boundary and coordinate tests.
- Modify: `tests/test_api.py:61-148` — add endpoint-level `413` and `422` tests.

**Interfaces:**
- Consumes: existing `Settings`, `parse_gpx_bytes`, and FastAPI `UploadFile`.
- Produces: `Settings.max_upload_bytes: int`, `Settings.max_route_points: int`, `parse_gpx_bytes(data: bytes, *, max_points: int | None = None) -> list[RoutePoint]`, and a private async `_read_upload(upload: UploadFile, *, max_bytes: int) -> bytes` helper in `app.py`.
- Error contract: define `UploadTooLargeError(ValueError)` in `app.py` or a small shared module; endpoint handlers map it to `HTTPException(status_code=413, ...)`. Parser point/coordinate errors remain `ValueError` and map to `422`.

- [ ] **Step 1: Write failing parser tests for point and coordinate limits**

Add tests in `tests/test_gpx.py` with a helper that builds a GPX byte payload from a requested point count. Pin exact boundary behavior:

```python
def test_parse_gpx_accepts_configured_point_limit() -> None:
    payload = make_gpx_bytes(4)
    points = parse_gpx_bytes(payload, max_points=4)
    assert len(points) == 4


def test_parse_gpx_rejects_point_above_limit() -> None:
    with pytest.raises(ValueError, match="maximum.*4"):
        parse_gpx_bytes(make_gpx_bytes(5), max_points=4)


@pytest.mark.parametrize("lat,lon", [(float("nan"), -122.0), (float("inf"), -122.0), (37.0, 180.1), (90.1, -122.0)])
def test_parse_gpx_rejects_invalid_coordinates(lat: float, lon: float) -> None:
    with pytest.raises(ValueError, match="coordinate"):
        parse_gpx_bytes(make_gpx_bytes(2, first=(lat, lon)))
```

Use valid numeric points for all non-target points so each test isolates one failure.

- [ ] **Step 2: Run parser tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_gpx.py -q
```

Expected: FAIL because `parse_gpx_bytes` does not accept `max_points` and currently does not reject invalid coordinates.

- [ ] **Step 3: Implement parser validation**

In `gpx.py`:

1. Add `import math`.
2. Change signature to `parse_gpx_bytes(data: bytes, *, max_points: int | None = None) -> list[RoutePoint]`.
3. Before appending each point, check `math.isfinite(lat)` and `math.isfinite(lon)`, then bounds `-90 <= lat <= 90` and `-180 <= lon <= 180`.
4. If `max_points` is set and `len(points) >= max_points` before appending another point, raise `ValueError("GPX route exceeds the maximum of {max_points} track points.")`.
5. Keep existing minimum-point and non-zero-distance checks.
6. Do not catch these validation errors inside the malformed-XML `try` block.

- [ ] **Step 4: Add settings fields and environment parsing**

In `config.py`, add frozen fields:

```python
max_upload_bytes: int = 5 * 1024 * 1024
max_route_points: int = 50_000
allow_unprotected_rendering: bool = False
```

Parse `MAX_UPLOAD_BYTES`, `MAX_ROUTE_POINTS`, and `ALLOW_UNPROTECTED_RENDERING` in `load_settings()`. Use a helper that raises `ValueError` for non-integer, zero, or negative limits instead of silently selecting a fallback. Treat `ALLOW_UNPROTECTED_RENDERING` as true only for case-insensitive values `1`, `true`, `yes`, or `on`.

Add:

```python
def validate_settings(settings: Settings) -> None:
    if settings.max_upload_bytes <= 0:
        raise ValueError("MAX_UPLOAD_BYTES must be greater than zero.")
    if settings.max_route_points < 2:
        raise ValueError("MAX_ROUTE_POINTS must be at least two.")
    if settings.environment.lower() == "production":
        recaptcha_ready = bool(settings.recaptcha_site_key and settings.recaptcha_secret_key)
        if not recaptcha_ready and not settings.allow_unprotected_rendering:
            raise ValueError(
                "Production requires RECAPTCHA_SITE_KEY and RECAPTCHA_SECRET_KEY "
                "or explicit ALLOW_UNPROTECTED_RENDERING=true."
            )
```

Call it in `load_settings()` before returning and in `create_app()` after selecting supplied or loaded settings. Keep local test settings valid.

- [ ] **Step 5: Add bounded upload helper and endpoint mapping**

In `app.py`, add:

```python
class UploadTooLargeError(ValueError):
    pass


async def _read_upload(upload: UploadFile, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(64 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(
                f"GPX upload exceeds the {max_bytes} byte limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)
```

Replace all three `await gpx_file.read()` calls with `_read_upload(..., max_bytes=app.state.settings.max_upload_bytes)`, and call `parse_gpx_bytes(..., max_points=app.state.settings.max_route_points)`.

Map `UploadTooLargeError` to `HTTPException(413, "GPX upload is too large.")`; map parser `ValueError` to existing `422` behavior. Do not include configured paths or raw parser internals in the oversized response.

- [ ] **Step 6: Write endpoint limit tests**

Add to `tests/test_api.py`:

```python
def test_parse_rejects_oversized_upload(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), max_upload_bytes=32)
    client = TestClient(create_app(settings=settings))
    response = client.post("/api/gpx/parse", files={"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")})
    assert response.status_code == 413
    assert response.json()["detail"] == "GPX upload is too large."


def test_parse_rejects_route_above_point_limit(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), max_route_points=2)
    client = TestClient(create_app(settings=settings))
    response = client.post("/api/gpx/parse", files={"gpx_file": ("route.gpx", VALID_GPX, "application/gpx+xml")})
    assert response.status_code == 422
    assert "maximum" in response.json()["detail"]
```

Use `dataclasses.replace` in the test module. Add endpoint tests for invalid coordinates through `/api/gpx/parse` and confirm `422`.

- [ ] **Step 7: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_gpx.py tests/test_api.py -q
```

Expected: PASS for new and existing tests. Existing tests may need settings construction updated with defaults only; do not change unrelated API behavior.

- [ ] **Step 8: Commit the input-boundary slice**

```bash
git add src/gpx_route_generator/config.py src/gpx_route_generator/gpx.py src/gpx_route_generator/app.py tests/test_gpx.py tests/test_api.py
git commit -m "feat: bound GPX uploads and route points"
```

---

### Task 2: Remove sensitive error leakage and correct public job contracts

**Files:**
- Modify: `src/gpx_route_generator/app.py:8-20,118-143,163-208,210-284,289-320` — add safe logging, sanitize preview/reCAPTCHA/render errors, return `202`, and distinguish failed jobs.
- Modify: `src/gpx_route_generator/jobs.py:28-35,47-59` — omit filesystem paths and provide consistent public snapshots.
- Modify: `src/gpx_route_generator/models.py:83-100` — validate strict `#RRGGBB` trail colors.
- Modify: `tests/test_api.py:105-241` — test safe errors, status contracts, malformed provider responses, and color validation.

**Interfaces:**
- Consumes: bounded input behavior from Task 1 and existing `JobStore`/`RenderJob`.
- Produces: `RenderJob.to_dict()` without `output_path`; `POST /api/render` with status `202`; `GET /api/jobs/{id}/video` with `409` only for queued/running jobs and `500` for failed jobs.
- Public error strings remain stable and generic; detailed exceptions are emitted through the module logger only.

- [ ] **Step 1: Write failing tests for public payload and status behavior**

Update existing assertions from `200` to `202` for render submission. Add:

```python
def test_job_payload_hides_output_path(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path), map_client_factory=lambda settings: SolidColorMapClient())
    response = post_render(TestClient(app))
    assert response.status_code == 202
    payload = response.json()
    assert "output_path" not in payload
    assert payload["download_url"] is None


def test_failed_job_video_is_terminal_error(tmp_path: Path) -> None:
    app = create_app(settings=make_settings(tmp_path))
    client = TestClient(app)
    job = RenderJob(
        id="failed",
        status="failed",
        output_path=tmp_path / "secret" / "route.mp4",
        estimated_map_requests=1,
        total_frames=1,
        error="Render failed.",
    )
    app.state.jobs.add(job)
    response = client.get("/api/jobs/failed/video")
    assert response.status_code == 500
    assert response.json()["detail"] == "Render failed."
```

Import `RenderJob` in the test module. Add a test that a failed job’s status payload contains no `/app/`, `output_path`, or injected exception details.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_api.py -q
```

Expected: FAIL because render currently returns `200`, job serialization includes `output_path`, and failed video requests return `409`.

- [ ] **Step 3: Sanitize `RenderJob.to_dict()`**

In `jobs.py`, stop calling `asdict(self)` for the public response because it serializes internal fields. Build an explicit dictionary containing only:

```python
{
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
    "download_url": f"/api/jobs/{self.id}/video" if self.status == "completed" else None,
}
```

Do not remove `output_path` from `RenderJob`; the renderer still needs it internally.

- [ ] **Step 4: Add logging and safe exception handling**

In `app.py`, import `logging` and define `logger = logging.getLogger(__name__)`.

Change preview’s broad exception branch to:

```python
except Exception:
    logger.exception("Preview render failed")
    raise HTTPException(
        status_code=500,
        detail="Preview could not be generated. Please try again.",
    ) from None
```

In `run_render_job`, log the exception with `logger.exception("Render job failed", extra={"job_id": job_id})` and store only `"Render failed. Please try again."` in the job.

Never log the API key or full provider URL. If logging an exception can include a URL, log only operation and job ID, not exception text.

- [ ] **Step 5: Harden reCAPTCHA response parsing**

In `verify_recaptcha`:

1. Call `response.raise_for_status()` after `requests.post`.
2. Catch `requests.RequestException`, `ValueError`, `TypeError`, and `KeyError` around status/JSON/score parsing.
3. Require `payload` to be a `dict`.
4. Convert score in a guarded block and return `HTTPException(502, "reCAPTCHA verification is temporarily unavailable.")` for malformed provider responses.
5. Keep valid unsuccessful verification as `400` and low score as `403`.

Add tests with fake responses for HTTP error, non-JSON response, non-dict JSON, and nonnumeric score. Fake response must implement `raise_for_status()` so the test pins the new contract.

- [ ] **Step 6: Fix API statuses and color validation**

Import `JSONResponse` and return `JSONResponse(status_code=202, content=job.to_dict())` from `start_render`.

In `job_video`:

```python
if job.status == "failed":
    raise HTTPException(status_code=500, detail=job.error or "Render failed.")
if job.status != "completed" or not job.output_path.exists():
    raise HTTPException(status_code=409, detail="Render video is not ready yet.")
```

In `validate_render_options`, enforce `^#[0-9a-fA-F]{6}$` using `re.fullmatch`. Raise `ValueError("Trail color must be a six-digit hex color such as #ff2f2f.")` for invalid values. Add API test with `trail_color="not-a-color"` expecting `422`.

- [ ] **Step 7: Add secret-leak regression test**

Create a fake `StaticMapClient` that raises `requests.HTTPError` containing a URL with `key=secret-google-key`, then call `/api/preview`.

Assert:

```python
assert response.status_code == 500
assert "secret-google-key" not in response.text
assert "http" not in response.text
assert "Preview could not be generated" in response.text
```

Use `caplog` only to confirm an error was logged; do not assert raw secret text appears in logs.

- [ ] **Step 8: Run focused tests and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_api.py tests/test_geo.py -q
```

Expected: PASS, including existing render completion tests updated for `202`.

Commit:

```bash
git add src/gpx_route_generator/app.py src/gpx_route_generator/jobs.py src/gpx_route_generator/models.py tests/test_api.py tests/test_geo.py
git commit -m "fix: sanitize public errors and job responses"
```

---

### Task 3: Harden Docker exposure and document safety settings

**Files:**
- Modify: `docker-compose.yml:1-13` — loopback binding and environment interpolation.
- Modify: `Dockerfile:1-26` — create and use non-root runtime user.
- Modify: `.env.example:1-10` — document safety settings and explicit production override.
- Modify: `tests/test_deployment.py` — add text/config regression checks.

**Interfaces:**
- Consumes: `MAX_UPLOAD_BYTES`, `MAX_ROUTE_POINTS`, and `ALLOW_UNPROTECTED_RENDERING` from Task 1.
- Produces: Docker Compose config that publishes `127.0.0.1:8000:8000`, honors `FRAME_WORKERS` overrides, and runs the app as `appuser`.

- [ ] **Step 1: Write failing deployment tests**

Create `tests/test_deployment.py`:

```python
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_compose_binds_port_to_loopback() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    assert '"127.0.0.1:8000:8000"' in compose
    assert '"8000:8000"' not in compose


def test_compose_allows_worker_override() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "${FRAME_WORKERS:-4}" in compose


def test_dockerfile_runs_non_root() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "useradd" in dockerfile
    assert "USER appuser" in dockerfile


def test_env_documents_limits_and_override() -> None:
    env_example = (ROOT / ".env.example").read_text()
    assert "MAX_UPLOAD_BYTES" in env_example
    assert "MAX_ROUTE_POINTS" in env_example
    assert "ALLOW_UNPROTECTED_RENDERING" in env_example
```

- [ ] **Step 2: Run deployment tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_deployment.py -q
```

Expected: FAIL because current Compose exposes all interfaces, hardcodes workers, Docker has no runtime user, and `.env.example` lacks new settings.

- [ ] **Step 3: Update Compose**

Change `docker-compose.yml` to:

```yaml
ports:
  - "127.0.0.1:8000:8000"
environment:
  PORT: 8000
  FRAME_WORKERS: ${FRAME_WORKERS:-4}
  MAX_UPLOAD_BYTES: ${MAX_UPLOAD_BYTES:-5242880}
  MAX_ROUTE_POINTS: ${MAX_ROUTE_POINTS:-50000}
  ALLOW_UNPROTECTED_RENDERING: ${ALLOW_UNPROTECTED_RENDERING:-false}
```

Keep the existing volume and restart policy.

- [ ] **Step 4: Run the container as non-root**

After creating `/app/data/jobs`, add:

```dockerfile
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app/data
USER appuser
```

Place `USER appuser` before `EXPOSE`, `VOLUME`, and `CMD`. Keep Uvicorn binding to `0.0.0.0` inside the container; Compose now controls host exposure.

- [ ] **Step 5: Document environment variables**

Add to `.env.example`:

```dotenv
# Maximum GPX upload size in bytes. Default: 5242880 (5 MiB).
# MAX_UPLOAD_BYTES=5242880

# Maximum track points accepted per GPX upload. Default: 50000.
# MAX_ROUTE_POINTS=50000

# Production must have reCAPTCHA keys unless this explicit override is enabled.
# Keep false for public deployments.
# ALLOW_UNPROTECTED_RENDERING=false
```

- [ ] **Step 6: Run deployment checks and commit**

Run:

```bash
.venv/bin/python -m pytest tests/test_deployment.py -q
docker compose config
```

Expected: deployment tests pass; rendered Compose config contains loopback binding, interpolated worker count, and configured safety limits.

Commit:

```bash
git add Dockerfile docker-compose.yml .env.example tests/test_deployment.py
git commit -m "chore: harden container exposure and runtime user"
```

---

### Task 4: Full verification and branch review

**Files:**
- Modify: `README.md` only if existing response-code or deployment instructions become inaccurate.
- Test: all files under `tests/`.

**Interfaces:**
- Consumes: all implementation slices from Tasks 1–3.
- Produces: verified branch with no unreviewed public-safety regressions.

- [ ] **Step 1: Run the complete test suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS. Existing Starlette/httpx deprecation warnings may remain; record them, do not hide them.

- [ ] **Step 2: Run static and dependency checks**

```bash
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m pip check
```

Expected: both commands exit `0`.

- [ ] **Step 3: Validate Compose and image build**

```bash
docker compose config
DOCKER_BUILDKIT=1 docker build --tag gpx-route-generator:safety-hardening .
```

Expected: Compose config succeeds and image builds. Do not push or deploy the image.

- [ ] **Step 4: Inspect the diff for scope leakage**

```bash
git diff main...HEAD --stat
git diff main...HEAD -- src/gpx_route_generator tests Dockerfile docker-compose.yml .env.example README.md
```

Confirm no camera, graph, trail, FFmpeg, queue, durable-storage, or rate-limit work was introduced accidentally. Confirm existing unrelated changes remain unmodified.

- [ ] **Step 5: Run GitNexus change detection**

Use the GitNexus change-detection tool against the branch. If the repository is still missing from the registry, record:

```text
GitNexus unavailable: GPX-Route-Generator is not indexed in the configured registry.
Direct source inspection and full test verification used instead.
```

Do not claim graph-based impact coverage.

- [ ] **Step 6: Review branch status and final evidence**

```bash
git status --short --branch
git log --oneline --decorate -5
```

Expected: branch is `safety/public-hardening`; only intended commits and pre-existing review artifacts remain. Report exact test outputs and any skipped checks.

- [ ] **Step 7: Request final code review before integration**

Run a fresh whole-branch review focused on:

1. secret and filesystem-path leakage,
2. bypasses around upload limits,
3. production fail-open configuration,
4. changed HTTP status behavior,
5. Docker host exposure and user permissions.

Do not merge, push, or deploy without explicit user direction.

## Plan Self-Review

### Spec coverage

- Bounded upload bytes: Task 1.
- Bounded route points: Task 1.
- Coordinate validation: Task 1.
- Safe preview and render errors: Task 2.
- No public filesystem path: Task 2.
- Production fail-closed behavior: Task 1.
- `202` render response: Task 2.
- Terminal failed video response: Task 2.
- Strict trail color: Task 2.
- Loopback Docker binding: Task 3.
- Non-root container: Task 3.
- Verification and GitNexus limitation: Task 4.

### Placeholder scan

No `TBD`, `TODO`, or unspecified implementation steps. Each task names files, interfaces, tests, commands, expected outcomes, and commit messages.

### Type consistency

- `Settings.max_upload_bytes`, `Settings.max_route_points`, and `Settings.allow_unprotected_rendering` are consumed by `create_app` and endpoint helpers.
- `parse_gpx_bytes(..., max_points=...)` is used by all three endpoints.
- `RenderJob.to_dict()` remains the public serializer while internal `output_path` remains available to `run_render_job` and `job_video`.
- `UploadTooLargeError` is endpoint-bound and does not alter parser `ValueError` semantics.

### Review focus coverage

- Chunked oversized upload: Task 1 endpoint/helper tests.
- Point-count boundary: Task 1 parser and API tests.
- Invalid coordinates: Task 1 parser and API tests.
- Provider exception containing secret URL: Task 2 preview regression test.
- Failed job containing filesystem path: Task 2 job payload and video tests.
