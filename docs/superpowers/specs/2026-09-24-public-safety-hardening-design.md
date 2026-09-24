# Public Safety Hardening — Design

Date: 2026-09-24
Branch: `safety/public-hardening`
Status: Approved for planning

## Problem

GPX Route Generator currently behaves as a trusted-local prototype while its
deployment story (`Dockerfile`, `docker-compose.yml`, README Lightsail
instructions) presents it as a deployable public service. Several paths let an
unauthenticated caller spend money, leak credentials, exhaust memory, or
receive misleading responses.

This slice fixes the immediate abuse and information-leak paths only. Render
performance and render capacity controls are separate slices.

## Goals

1. Bound every request input before expensive work happens.
2. Stop leaking secrets, filesystem paths, and raw exception text to clients.
3. Make incomplete production protection fail at startup instead of silently
   disabling reCAPTCHA.
4. Correct API contract errors that mislead clients.
5. Stop publishing the container port on all host interfaces.

## Non-goals

Explicitly out of scope for this slice:

- Render admission control, queueing, or global concurrency limits.
- FFmpeg timeout, process-group termination, and stderr draining.
- Camera planning, trail, and metric-graph algorithmic work.
- Durable job storage or job recovery across restart.
- Rate limiting, authentication, or per-client quotas.
- Browser-side preview cancellation and preview/map caching.

These remain queued for later slices and must not be partially implemented
here.

## Design

### 1. Input limits

Add a single bounded read helper used by every GPX upload endpoint. It reads
the upload in chunks, aborts as soon as the byte budget is exceeded, and raises
a distinct error type so the API can answer `413`.

New settings (environment driven, with conservative defaults):

| Setting | Environment variable | Default |
|---|---|---|
| `max_upload_bytes` | `MAX_UPLOAD_BYTES` | 5 MiB |
| `max_route_points` | `MAX_ROUTE_POINTS` | 50,000 |

Parser changes in `gpx.py`:

- Reject payloads above the byte budget before decoding.
- Enforce the point cap while collecting points, before any distance work.
- Reject non-finite coordinates.
- Reject latitude outside `[-90, 90]` and longitude outside `[-180, 180]`.
- Preserve the existing "at least two points" and "non-zero distance" rules.

Error mapping:

| Condition | Status |
|---|---|
| Upload exceeds byte budget | `413` |
| Point count exceeds cap | `422` |
| Invalid or out-of-range coordinates | `422` |
| Malformed GPX | `422` |

`/api/gpx/parse` currently serializes every point. With the point cap in place
the response is bounded, so no pagination is added in this slice.

### 2. Safe errors

- `/api/preview` returns a fixed public message on unexpected failure and logs
  the real exception server-side.
- Failed render jobs store a stable public message; the detailed exception goes
  to the log.
- `RenderJob.to_dict()` stops exposing `output_path`; `download_url` remains the
  public handle.
- The Google Maps API key must never appear in a response body. Any provider
  failure message returned to a client is a fixed string.

A module-level logger is introduced (`logging.getLogger(__name__)`) since the
project has no logging today. Logging stays at the application level; no
metrics, tracing, or log shipping are added in this slice.

### 3. Production fail-closed

Today `recaptcha_enabled` is false whenever either reCAPTCHA key is missing,
including in `APP_ENV=production`. That silently removes protection from
`/api/render`.

New behavior:

- In production, startup fails when reCAPTCHA is not fully configured, unless
  the operator explicitly sets `ALLOW_UNPROTECTED_RENDERING=true`.
- `local` and other non-production environments keep the current permissive
  behavior, so development and tests are unaffected.

Validation lives in `config.py` and runs from `load_settings()` and from
`create_app()` when settings are supplied directly, so tests that construct
`Settings` by hand are also covered.

`/api/preview` continues to be reachable without reCAPTCHA in this slice. That
is a known, accepted gap recorded in the non-goals.

### 4. API contract fixes

| Change | Location | Rationale |
|---|---|---|
| Render submission returns `202` | `start_render` | Work is queued, not finished |
| Failed job video returns a terminal error, not "not ready" | `job_video` | Callers must distinguish failure from in-progress |
| Queued/running job video stays `409` | `job_video` | Preserve current polling behavior |
| reCAPTCHA non-JSON or invalid-score responses return `502` | `verify_recaptcha` | Provider failure is not a client failure |
| `trail_color` must match `#RRGGBB` or render returns `422` | `validate_render_options` | Renderer currently substitutes red silently |

Renderer color fallback stays as internal defense but becomes unreachable via
the API.

### 5. Deployment boundary

- `docker-compose.yml` binds `127.0.0.1:8000:8000` so a direct connection cannot
  bypass the documented reverse proxy.
- `Dockerfile` gains a non-root user that owns `/app/data`; the container runs as
  that user.

## Testing

New and updated tests, written before implementation:

1. Oversized upload returns `413` on `/api/gpx/parse`, `/api/preview`, and
   `/api/render`.
2. Route above the point cap returns `422`.
3. Non-finite and out-of-range coordinates return `422`.
4. `/api/preview` provider failure returns a body that does not contain the API
   key or an internal path.
5. Failed job payload contains no `output_path` and no raw exception text.
6. Production settings without reCAPTCHA keys fail validation; with
   `ALLOW_UNPROTECTED_RENDERING=true` they succeed.
7. `/api/render` returns `202`.
8. Video request for a failed job returns a terminal status, not `409`.
9. Malformed reCAPTCHA payload returns `502`.
10. Invalid `trail_color` returns `422`.
11. Bounded read helper stops early instead of materializing an oversized body.

Existing tests that assert `200` from `/api/render` must be updated to `202`.

## Verification gate

- `.venv/bin/python -m pytest -q` passes.
- `.venv/bin/python -m pip check` passes.
- `python -m compileall -q src tests` passes.
- `docker compose config` shows the loopback port binding.
- Diff reviewed to confirm no other findings were partially implemented.
- GitNexus impact analysis run before editing symbols if the index becomes
  available; otherwise the unavailability is recorded in the final report.

## Risks

- Rejecting coordinates that previously rendered could break existing user
  files. Mitigation: latitude is currently clamped, not rejected; only
  genuinely invalid values are rejected, and the error message names the
  offending point.
- Returning `202` changes a documented response code. Mitigation: this is a
  correctness fix and the UI reads the JSON body, not the status code.
- Startup failure in production is a behavior change. Mitigation: it is gated on
  `APP_ENV=production` and has an explicit override.
