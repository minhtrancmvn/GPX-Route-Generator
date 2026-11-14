# Production deployment

## Pipeline

Matches Task Automation's Lightsail pattern: GitHub-hosted runner, pinned SSH host keys, SHA-addressed release directories, server-local secrets, and atomic `current` symlink activation. Uses the same `lightsail-production` environment and `LIGHTSAIL_*` settings names; GitHub secrets are repository/environment scoped and are not automatically shared between repositories. Unlike Task Automation's cron processes, GPX runs a long-lived Docker service with FFmpeg and health checks.

Existing `Quality` workflow tests Python, runs fatal Ruff checks, and builds Docker image on pushes and pull requests. `Deploy production` runs only after a successful `Quality` run for a push to this repository's `main`. It checks the tested SHA is still current, uploads that exact checkout over SSH to the host's deploy gate, builds on the Linux host, and waits for a protected app to become healthy.

The CI key is pinned to `/opt/gpx-route-generator/deploy/deploy-gate` with `restrict,command=` in `authorized_keys`: it can only run `upload <sha>` (unpack a `git archive` into `releases/<sha>`) or `activate <sha>`. Activation runs the host's own root-owned copies of `deploy.sh` and `compose.production.yml`; the uploaded release is only the Docker build context, so nothing in a release decides how the container runs or touches nginx. Change those files here, then re-run `setup-host.sh` on the host to install them. Pull requests cannot trigger deployment. Deployment jobs serialize without cancellation so a running activation is not interrupted.

No server credentials, application secrets, or Cloudflare credentials belong in source control. SSH host keys are pinned; do not replace this with runtime `ssh-keyscan` or disable host verification.

## One-time host setup

Install Docker Engine, Docker Compose v2 with `up --wait`, Bash, `flock`, GNU coreutils, and tar. The admin account that runs the gate needs Docker access; Docker-group membership is effectively root access, which is why the CI key only reaches the gate. Then copy `deploy/` to the host and, as the admin user, run:

```bash
bash setup-host.sh                                              # layout, scripts, compose file, .env, vhost
CI_PUBLIC_KEY="ssh-ed25519 AAAA... comment" bash setup-host.sh  # also pin the CI key to the gate
``` No inbound app port is required beyond your existing reverse proxy; SSH must be reachable from GitHub-hosted runners or use a separately approved private runner arrangement.

Directory layout `setup-host.sh` creates:

```text
/opt/gpx-route-generator/
  .env                       mode 600, admin user
  deploy/                    root-owned: deploy-gate, deploy.sh, compose.production.yml
  releases/<commit-sha>/     uploaded sources (Docker build contexts)
  current -> releases/<healthy-commit-sha>
```

`/opt/gpx-route-generator/.env` holds the production values; the host's compose file reads it directly, and secrets never enter a release. Copy variable names from repository `.env.example`, then set real values locally on that host. Do not upload development `.env` from a laptop. Required names:

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

Set `SSH_PORT` if the default `22` does not fit. Host names, the user and the SHA are validated before being embedded in remote commands. Current Lightsail host already has Docker Compose, root-level `.env`, SSH key, Nginx redirect vhost, and GPX TLS certificate provisioned. For a nonstandard SSH port, known_hosts must use `[hostname]:port` format. Never paste private keys into issue comments, chat, or source files.

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
3. Run `setup-host.sh` (installs the gate, scripts, compose file and GPX Nginx vhost, and pins the CI key), then merge to `main`; that merge triggers the next production activation.
4. Confirm GitHub workflows pass, container becomes healthy, and Waybill remains available.
5. Check public GPX API and perform one real CAPTCHA-protected render. Do not expose config containing site key; Maps and reCAPTCHA secrets remain server-only.

Read-only host checks:

```bash
DEPLOY_ROOT=/opt/gpx-route-generator GPX_RELEASE="$(readlink -f /opt/gpx-route-generator/current)" \
  docker compose --project-name gpx-route-generator \
  --env-file /opt/gpx-route-generator/.env \
  -f /opt/gpx-route-generator/deploy/compose.production.yml ps
curl --fail --silent https://gpx-route-generator.minhtran.id.vn/api/config
```

## Failure and rollback

Script builds before replacing app. A failed build leaves running release untouched. A failed health check attempts to restart previous healthy release without rebuilding, then fails CI. On first deployment with no previous release, failed activation stops GPX container and leaves Waybill and other apps untouched. First deployment has no previous release to restore. `current` changes only after health check succeeds. Deployments restart process; queued/running jobs are in memory and are not preserved across restarts. Plan deploys when no renders are active. Render files remain in named `gpx-route-generator-data` volume; never run `docker compose down --volumes` as rollback.

After each successful activation, `prune-releases.sh` keeps the 5 newest release directories plus any from the last 7 days (never the active one), and `deploy.sh` removes each `gpx-route-generator:<sha>` image whose release directory is gone. Nothing else is pruned: do not run Docker prune on a shared host.

Manual rollback requires approval because it restarts production. Activate a retained healthy release by its full SHA:

```bash
/opt/gpx-route-generator/deploy/deploy-gate activate <healthy-sha>
```
