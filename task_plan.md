# Task Plan: Production security audit and CI/CD

## Goal
Verify existing CAPTCHA and exposed credentials, then configure tested deployment on pushes to main using Task Automation deployment conventions for gpx-route-generator.minhtran.id.vn.

## Phases
- [x] Phase 1: Inspect CAPTCHA, scan source and Git history, and inspect reference deployment
- [x] Phase 2: Choose deployment approach and run required graph impact analysis
- [x] Phase 3: Implement CI/CD and deployment configuration on feature branch
- [x] Phase 4: Validate local tests, workflows, deployment configuration, and report activation blockers (live deployment unverified)

## Key Questions
1. Does any form have client-side and server-side CAPTCHA verification?
2. Are real secrets exposed in tracked files, reachable Git history, or generated frontend output?
3. Which host, transport, and secrets conventions does Task Automation use?
4. Which infrastructure changes require explicit user confirmation?

## Decisions Made
- Work on feat/production-ci-cd; no commits, pushes, remote writes, or production restarts without authorization.
- Preserve prior completed plan in Git history; this plan tracks current request.
- Redact credential values from all reports and command output.

## Errors Encountered
- Initial tool inventory command exited 1 because gitleaks/actionlint were not found on PATH; installed Gitleaks, actionlint, and shellcheck through Homebrew.
- Docker daemon unavailable; local image build and container activation cannot run. Docker Compose plugin absent; installed standalone docker-compose and validated config without running containers.
- Existing local venv lacks Ruff; uvx ruff passed fatal checks.
- Deployment contract tests initially failed because implementation files did not exist (expected red phase); subsequent tests passed.
- actionlint initially reported SC2029 for intentional validated local expansion in SSH remote commands; documented targeted suppression and reran clean.
- Cloudflare account returned no matching zone; no infrastructure writes attempted.
- Graph change detection sees tracked diffs only (2 files); new untracked deployment files were not covered. No commit attempted.
- Completed audit/review worktrees auto-removed by harness; direct status checks confirmed those directories no longer exist.

## Activation follow-up
- [x] Inspect same Lightsail host, SSH access, existing proxy, resources, and credential availability
- [x] Provision isolated GPX runtime and GitHub deployment settings without disturbing existing apps (candidate build and protected-config check passed; production activation pending)
- [x] Install explicit default vhost redirect to https://minhtran.id.vn. GPX hostname Nginx route installs on first successful deployment. Verified unknown-host HTTPS 302 and Waybill HTTPS 200.
- User confirmed same Lightsail host and approved provisioning/routing on 2026-10-23. No commit or push authorization yet. Never print or copy unrelated Task Automation application secrets.
- Host: Ubuntu 24.04, 2 GiB RAM, 58 GiB disk. Installed Docker 29.1.3 and Compose 2.40.3; enabled Docker and added ubuntu user to docker group.
- User requested production project root match existing `/home/ubuntu` layout. Final root `/home/ubuntu/gpx-route-generator`; `.env` at root (0600), beside `releases/` and `current`. Temporary `/opt` directory and validation source removed; no remaining `/opt/gpx-route-generator`.
- Copied only Maps key and reCAPTCHA site/secret keys from ignored local `.env`; values never printed. Production uses FRAME_WORKERS=1 and MAX_ACTIVE_PREVIEWS=1 for host capacity.
- Candidate image built successfully and ran in isolated validation container; app startup and `/api/config` confirmed reCAPTCHA enabled and Maps key configured. Temporary container removed.
- Candidate commit `8d2f79b355a00b5bf65df25cdd6bb1b638d0a1a6` temporarily uploaded to `/home/ubuntu/gpx-route-generator/releases/` as pre-merge validation, built and tested, then removed. No release remains and no production container is active; next activation must use merged main SHA.
- Created unique GPX ed25519 deploy key with `restrict` authorized_keys option. Configured new GitHub `lightsail-production` environment, its `LIGHTSAIL_*` secrets and variables. No existing Task Automation credentials were read/copied.
- Added installed Nginx default vhosts: unknown HTTP/HTTPS hosts now 302 to `https://minhtran.id.vn/`; separate named Waybill vhost remains unchanged. Verified both default redirects and Waybill HTTP 200 locally through Nginx. Public GPX hostname is currently covered by default redirect until own vhost activation.
- Issued Let's Encrypt cert for GPX hostname. Installed HTTP-only ACME challenge vhost; public HTTPS GPX stays default redirect until reviewed branch deploys. Certbot renewal deploy hook tests/reloads Nginx.
- Added `deploy/nginx-gpx.conf` route target 127.0.0.1:8001 with 6 MiB body limit, `/home/<user>` path allowlist, and atomic Nginx config install/rollback in activation script. It becomes active only when deployment workflow runs after main merge.
- GitHub `lightsail-production` env created, secrets/variables configured for same host, branch policy restricted to main. Dedicated ed25519 SSH key is host-authorized with `restrict` option. Names/details in GitHub; private key stays local.
- Local GPX `.env` contains configured keys and reCAPTCHA site key is not Google's published test key; production test render still required after deployment.
- Home candidate image tested in isolated container with production credentials: app starts and API confirms protection and key configured. An initial test failed due JSON-quoted Docker .env values; corrected on host and test passed. Another probe mismatch expected health metadata in a manual docker run without Compose; container was then removed. Compose production health check remains intact.
- Initial Mac tar archive carried AppleDouble metadata; uploaded USTAR archive without resource forks. No secrets embedded in release archives; `.env` excluded by Git/archive.
- GitHub env API first policy call malformed and branch-policy POST returned 404 before environment branch policy enabled; subsequent update enabled custom policies and installed main-only policy.
- Moving `.env` to root per user request complete; local test assertion initially stale about readlink count, fixed; next regression assertion initially matched rollback setup symlink before activation. Changed to `rindex`; rerun passes.
- Temporary `/tmp/gpx-route-release*.tar.gz` files and local deploy key exist in local workdir/home; retain key for CI maintenance or remove via `rm ~/.ssh/gpx-route-generator-deploy*` when no longer needed.
- Issued Let's Encrypt certificate for gpx-route-generator.minhtran.id.vn (expires 2027-01-21); automatic certbot timer enabled and installed deploy hook validates/reloads Nginx on renewal.
- Host provisioning changed sudoers? No. Docker group is privileged by nature; ubuntu account now belongs to Docker group and deployment key is restricted in authorized_keys.
- Production vhost template deploy/nginx-gpx.conf separates GPX hostname and preserves ACME challenge; not yet installed, pending healthy container start.
- Candidate Docker image `gpx-route-generator:validation` built and tested; no production container or Waybill service touched.
- User explicitly authorized same-host provisioning and hostname/default routing changes. Commit or push remains unauthorized. First deploy requires merge to main; do not manually activate candidate.
- Final run after all path/routing changes: 199 passed, actionlint/shellcheck/Ruff/compileall/pip check/Compose config/diff checks passed. Candidate image built and protected config verified. Production activation intentionally waits for reviewed merge to main.


## Status
**Prepared; waiting for main merge** - 199 tests pass. Host root, root `.env`, deployment SSH key, GitHub environment, cert, and unknown-host redirect configured. Candidate image built and passed isolated production-config check. Workflow will deploy only after merge/push to `main`; production GPX app/vhost remain inactive. No commit or push yet.

## Evidence and remaining work
- Gitleaks 8.30.1 scanned 102 reachable commits: zero findings. Working scan found four credential-pattern matches only in ignored .env; copied secret-bearing scan workspace removed, redacted reports retained in /tmp/gpx-secret-audit.
- reCAPTCHA v3 protects render only; backend validates success and score but not action/hostname. Preview and parsing remain outside CAPTCHA coverage. Application code unchanged.
- Reference Task Automation .github/workflows/deploy-lightsail.yml and deploy/activate-release.sh use GitHub-hosted runners, LIGHTSAIL_* settings, SHA releases, server-local secrets, atomic current symlink. GPX now follows same conventions with Docker health checks and rollback.
- GitNexus impact: docker-compose.yml and README.md LOW, zero graph callers/processes. quality.yml UNKNOWN/unresolved by graph; literal search confirms tests/test_ci_workflow.py reads it. Added validation steps preserve existing quality/docker jobs.
- Final graph detect-changes: 3 tracked files, 9 symbols, zero affected processes, LOW. New untracked deployment files not covered; deterministic YAML/shell/config/tests validate these separately.
- Full pytest -v evidence: /tmp/gpx-deployment-pytest.txt (197 passed, existing Starlette/httpx deprecation warning). Python 3.14 locally; CI retains Python 3.11.
- GitHub environment `lightsail-production` configured and restricted to `main`; secrets and variables set. Existing Preview and Production environments left untouched.
- Production host provisioned at `/home/ubuntu/gpx-route-generator`, with root `.env` mode 600, Docker/Compose, unique restricted SSH deploy key, and named persistent volume to be created on first activation. Public GPX vhost will map only hostname to loopback port 8001; Waybill vhost untouched.
- Independent config review found relative-symlink rollback mismatch; fixed with readlink -f and regression test. Rechecks main SHA after upload; main can still advance during host build, so deployment may briefly run an earlier CI-green revision until subsequent deployment.
- All agent worktrees auto-removed by harness; git worktree prune/list confirms only primary worktree remains.
- Reference agent exceeded timebox and was stopped; inspected two exact reference files directly afterward.
- Final shell check initially failed because zsh status is read-only; renamed/removed variable and reran successfully.
- Final diff check found extra blank line at EOF in this plan; removed and reran.
