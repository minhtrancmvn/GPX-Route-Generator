# Production deployment

## Pipeline

Matches Task Automation's Lightsail pattern: GitHub-hosted runner, pinned SSH host keys, SHA-addressed release directories, server-local secrets, and atomic `current` symlink activation. Uses the same `lightsail-production` environment and `LIGHTSAIL_*` settings names; GitHub secrets are repository/environment scoped and are not automatically shared between repositories. Unlike Task Automation's cron processes, GPX runs a long-lived Docker service with FFmpeg and health checks.

Existing `Quality` workflow tests Python, runs fatal Ruff checks, and builds Docker image on pushes and pull requests. `Deploy production` runs only after a successful `Quality` run for a push to this repository's `main`. It checks the tested SHA is still current, uploads that exact checkout over SSH, builds on the Linux host, and waits for a protected app to become healthy. Pull requests cannot trigger deployment. Deployment jobs serialize without cancellation so a running activation is not interrupted.

No server credentials, application secrets, or Cloudflare credentials belong in source control. SSH host keys are pinned; do not replace this with runtime `ssh-keyscan` or disable host verification.

## One-time host setup

Use a dedicated Linux deployment directory and account. Install Docker Engine, Docker Compose v2 with `up --wait`, Bash, `flock`, GNU coreutils, and tar. The deployment account needs Docker access; Docker-group membership is effectively root access. Restrict its SSH key and GitHub production environment accordingly. No inbound app port is required beyond your existing reverse proxy; SSH must be reachable from GitHub-hosted runners or use a separately approved private runner arrangement.

Example directory layout (create with appropriate owner and mode, not world-writable):

```text
/home/ubuntu/gpx-route-generator/
  .env
  releases/<commit-sha>/
  current -> releases/<healthy-commit-sha>
```

Create `/home/ubuntu/gpx-route-generator/.env` beside `releases/` and `current`, mode `600`, owned by deployment account. The shared Lightsail environment has this file at that exact path. Each deployed release receives a `.env` symlink to this root file before activation, matching Task Automation's layout without copying secrets into release source. Copy variable names from repository `.env.example`, then set real values locally on that host. Do not upload development `.env` from a laptop. Required names:

```dotenv
APP_ENV=production
ALLOW_UNPROTECTED_RENDERING=false
GOOGLE_MAPS_API_KEY=<server-side Maps Static API key>
RECAPTCHA_SITE_KEY=<reCAPTCHA v3 public site key>
RECAPTCHA_SECRET_KEY=<reCAPTCHA v3 server secret>
GPX_PORT=8001
```

Replace angle-bracket values before use. Register `gpx-route-generator.minhtran.id.vn` in Google's reCAPTCHA v3 console. Restrict Maps key to Maps Static API and production server's outbound IP where supported; set quota/billing alerts. Site key is public by design. Maps key and CAPTCHA secret must never appear in browser assets.

Production Compose forces `APP_ENV=production` and disables unsafe bypass even when server env file contains local defaults. Missing or empty API/CAPTCHA keys fail Compose validation before replacing running container. Health probe checks `/api/config`, CAPTCHA enabled, Maps key present, and GPX avatar metadata. It does not prove Google accepts configured keys: verify one real render after activation.

## GitHub configuration

`lightsail-production` environment is configured for `main` only. Add required reviewers there if desired. Configured secrets:

| Secret | Purpose |
| --- | --- |
| `LIGHTSAIL_SSH_PRIVATE_KEY` | Private key authorized for deployment account |
| `LIGHTSAIL_KNOWN_HOSTS` | Pinned OpenSSH known_hosts entry, verified through trusted host console |

Configured environment variables: `LIGHTSAIL_HOST`, `LIGHTSAIL_USER`.

Set environment variables if defaults do not fit:

| Variable | Default |
| --- | --- |
| `SSH_PORT` | `22` |
| `DEPLOY_ROOT` | `/home/ubuntu/gpx-route-generator` |

Host names and paths are validated before being embedded in remote commands. Deployment roots must be absolute paths below `/home/<user>/`, containing only letters, digits, slash, underscore, and hyphen. Default root matches existing Lightsail apps: `/home/ubuntu/gpx-route-generator`. Current Lightsail host already has Docker Compose, root-level `.env`, SSH key, Nginx redirect vhost, and GPX TLS certificate provisioned. For a nonstandard SSH port, known_hosts must use `[hostname]:port` format. Never paste private keys into issue comments, chat, or source files.

Protect `main` with required `Tests and checks` and `Docker build` checks. This workflow gates deployment on successful CI even without branch protection, but does not prevent direct pushes. Add least-privilege repository settings separately; configuration here does not change remote policy.

## Domain routing

DNS resolution alone does not bind a hostname to GPX. At audit time, `https://gpx-route-generator.minhtran.id.vn/` served a page titled `Waybill Generator`; `/api/config` returned HTML. Host routing was verified on the shared Lightsail instance, preserving the named Waybill vhost.

On the app host, proxy only this hostname to `http://127.0.0.1:8001`. Default GPX port is `8001` to avoid colliding with existing services using `8000`. For host-installed cloudflared, add a hostname-specific ingress rule before wildcard/catch-all rules:

```yaml
ingress:
  - hostname: gpx-route-generator.minhtran.id.vn
    service: http://127.0.0.1:8001
  # Keep other existing hostname rules here.
  - service: http_status:404
```

Merge this example into existing ingress configuration; do not replace other routes. For a remotely managed Cloudflare Tunnel, configure the same public hostname and origin service in its dashboard. A containerized tunnel cannot reach another container via its own `127.0.0.1`; use an approved shared Docker network or host gateway instead. For Nginx/Caddy, use a host-specific virtual host and preserve existing applications.

Cloudflare MCP account did not list the `minhtran.id.vn` zone, so DNS was not changed. Host routing uses Nginx on the same Lightsail host as Task Automation. `nginx-gpx.conf` is the hostname-specific GPX vhost; `nginx-default.conf` makes unmatched HTTP/HTTPS hosts redirect to `https://minhtran.id.vn` instead of falling through to Waybill. TLS certificate verification happens before an HTTPS redirect, so arbitrary unknown hostnames may still encounter certificate errors unless the edge handles their TLS. Keep existing named Waybill vhost unchanged.

### Direct upload host

Some ISPs (seen with Viettel) stall uploads to Cloudflare's edge while downloads work, so preview and render uploads go to `gpx-upload.minhtran.id.vn` instead. That hostname is a **DNS-only** (grey cloud) `A` record pointing at the Lightsail static IP; the page itself stays proxied. Its Nginx vhost in `nginx-gpx.conf` accepts only `POST /api/preview` and `POST /api/render` and returns 404 for everything else. It sends `Access-Control-Allow-Origin` for the page's origin only. A DNS-only record exposes the server IP.

Enable it after the DNS record and its Let's Encrypt certificate exist (the vhost references the certificate, so Nginx validation fails without it): set `UPLOAD_ORIGIN=https://gpx-upload.minhtran.id.vn` in the root `.env` and redeploy. Leaving `UPLOAD_ORIGIN` unset uploads to the page origin.

## Activation and verification

1. Shared Lightsail host is provisioned; isolated deployment key, root `.env`, Docker and Compose are ready. Candidate image passed isolated app startup/config check.
2. `lightsail-production` GitHub environment is restricted to `main`, with deployment secrets and variables configured.
3. Merge deployment workflow to `main`; that merge triggers first production activation and installs GPX Nginx vhost.
4. Confirm GitHub workflows pass, container becomes healthy, and Waybill remains available.
5. Check public GPX API and perform one real CAPTCHA-protected render. Do not expose config containing site key; Maps and reCAPTCHA secrets remain server-only.

Read-only host checks:

```bash
cd /home/ubuntu/gpx-route-generator/current
DEPLOY_ROOT=/home/ubuntu/gpx-route-generator \
  docker compose --project-name gpx-route-generator \
  --env-file /home/ubuntu/gpx-route-generator/.env \
  -f /home/ubuntu/gpx-route-generator/current/deploy/compose.production.yml ps
curl --fail --silent https://gpx-route-generator.minhtran.id.vn/api/config
```

## Failure and rollback

Script builds before replacing app. A failed build leaves running release untouched. A failed health check attempts to restart previous healthy release without rebuilding, then fails CI. On first deployment with no previous release, failed activation stops GPX container and leaves Waybill and other apps untouched. First deployment has no previous release to restore. `current` changes only after health check succeeds. Deployments restart process; queued/running jobs are in memory and are not preserved across restarts. Plan deploys when no renders are active. Render files remain in named `gpx-route-generator-data` volume; never run `docker compose down --volumes` as rollback.

Release directories and old Docker images are retained to support rollback. Monitor disk and remove old releases/images only after confirming they are not current or needed for rollback. Do not blindly run Docker prune on a shared host.

Manual rollback requires approval because it restarts production. Run script from a retained healthy release with its full SHA:

```bash
bash /home/ubuntu/gpx-route-generator/releases/<healthy-sha>/deploy/deploy.sh \
  /home/ubuntu/gpx-route-generator <healthy-sha>
```
