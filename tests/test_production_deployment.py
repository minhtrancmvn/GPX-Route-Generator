import io
from pathlib import Path
import subprocess
import urllib.request

import pytest
import yaml


ROOT = Path(__file__).parents[1]


def test_deployment_runs_only_after_main_quality_succeeds() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert triggers["workflow_run"]["workflows"] == ["Quality"]
    assert triggers["workflow_run"]["types"] == ["completed"]
    assert triggers["workflow_run"]["branches"] == ["main"]
    job = workflow["jobs"]["deploy"]
    assert "github.event.workflow_run.conclusion == 'success'" in job["if"]
    assert "github.event.workflow_run.event == 'push'" in job["if"]
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in job["if"]
    assert job["environment"] == "lightsail-production"
    assert job["timeout-minutes"] <= 15
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_production_compose_fails_closed_and_persists_jobs() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.production.yml").read_text())
    app = compose["services"]["app"]
    assert app["env_file"] == ["${DEPLOY_ROOT:?Set DEPLOY_ROOT to the deployment root}/.env"]
    assert app["environment"]["APP_ENV"] == "production"
    assert app["environment"]["ALLOW_UNPROTECTED_RENDERING"] == "false"
    assert app["environment"]["GOOGLE_MAPS_API_KEY"].startswith("${GOOGLE_MAPS_API_KEY:?")
    assert app["environment"]["RECAPTCHA_SITE_KEY"].startswith("${RECAPTCHA_SITE_KEY:?")
    assert app["environment"]["RECAPTCHA_SECRET_KEY"].startswith("${RECAPTCHA_SECRET_KEY:?")
    assert app["environment"]["RECAPTCHA_SITE_KEY"].startswith("${RECAPTCHA_SITE_KEY:?")
    assert app["environment"]["RECAPTCHA_SECRET_KEY"].startswith("${RECAPTCHA_SECRET_KEY:?")
    assert app["ports"] == ["127.0.0.1:${GPX_PORT:-8001}:8000"]
    assert app["volumes"] == ["app-data:/app/data"]
    assert compose["volumes"]["app-data"]["name"] == "gpx-route-generator-data"
    assert app["restart"] == "unless-stopped"
    assert "healthcheck" in app
    assert "build" in app


def test_health_probe_checks_application_identity_and_protection() -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.production.yml").read_text())
    probe = compose["services"]["app"]["healthcheck"]["test"]
    assert probe[0] == "CMD"
    assert "/api/config" in probe[-1]
    assert "recaptcha_enabled" in probe[-1]
    assert "has_google_maps_key" in probe[-1]


def test_deploy_uses_host_key_verification_and_never_uploads_local_env() -> None:
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
    assert "StrictHostKeyChecking=yes" in workflow
    assert "SSH_KNOWN_HOSTS" in workflow
    assert 'git archive --format=tar' in workflow
    assert '"$DEPLOY_SHA"' in workflow
    assert 'tar --exclude' not in workflow
    script = (ROOT / "deploy/deploy.sh").read_text()
    assert 'GPX_ENV_FILE="$root/.env"' in script
    assert 'ln -sfn "$GPX_ENV_FILE" "$release/.env"' in script
    assert "Production .env must have mode 600" in script
    assert 'readlink -f "$root/current"' in script
    assert "ssh-keyscan" not in workflow
    assert "StrictHostKeyChecking=no" not in workflow
    assert "head_sha" in workflow
    assert "gh api" in workflow
    assert "git archive --format=tar" in workflow
    assert workflow.count('gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"') == 2


def test_rollback_resolves_relative_current_symlink() -> None:
    script = (ROOT / "deploy/deploy.sh").read_text()
    assert 'readlink -f "$root/current"' in script
    assert 'up --detach --no-build --wait --wait-timeout 120' in script
    assert script.index('"${compose[@]}" build --pull') < script.index('"${compose[@]}" up')
    assert script.rindex('"${compose[@]}" up --detach --remove-orphans') < script.rindex('ln -sfn "$release"')


@pytest.mark.parametrize("body,healthy", [
    (b'{"recaptcha_enabled":true,"has_google_maps_key":true,"recaptcha_site_key":"public","avatars":["bike"]}', True),
    (b'{"recaptcha_enabled":false,"has_google_maps_key":true,"recaptcha_site_key":"public","avatars":["bike"]}', False),
    (b'{"recaptcha_enabled":true,"has_google_maps_key":false,"recaptcha_site_key":"public","avatars":["bike"]}', False),
    (b'<html><title>Waybill Generator</title></html>', False),
])
def test_health_probe_rejects_unprotected_or_wrong_app(monkeypatch, body, healthy) -> None:
    compose = yaml.safe_load((ROOT / "deploy/compose.production.yml").read_text())
    probe = compose["services"]["app"]["healthcheck"]["test"][-1]
    monkeypatch.setattr(urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(body))
    if healthy:
        exec(probe, {})
    else:
        with pytest.raises((AssertionError, ValueError)):
            exec(probe, {})


@pytest.mark.parametrize("root,sha,message", [
    ("/opt/gpx-route-generator", "a" * 40, "Invalid deployment root"),
    ("/home/ubuntu/gpx-route-generator", "not-a-sha", "Invalid commit SHA"),
])
def test_activation_rejects_invalid_arguments_before_docker(root, sha, message) -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/deploy.sh"), root, sha],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert message in result.stderr


def test_default_vhost_redirects_unknown_hosts_without_proxying_waybill() -> None:
    config = (ROOT / "deploy/nginx-default.conf").read_text()
    assert "listen 80 default_server;" in config
    assert "listen 443 ssl default_server;" in config
    assert config.count("return 302 https://minhtran.id.vn;") == 2
    assert "proxy_pass" not in config


def test_gpx_vhost_routes_only_named_host_and_preserves_acme_challenge() -> None:
    config = (ROOT / "deploy/nginx-gpx.conf").read_text()
    assert config.count("server_name gpx-route-generator.minhtran.id.vn;") == 2
    assert "default_server" not in config
    assert "proxy_pass http://127.0.0.1:8001;" in config
    assert "location ^~ /.well-known/acme-challenge/" in config
    # Above the 10 MiB app limit plus multipart overhead, so the app returns its own 413.
    assert "client_max_body_size 11m;" in config
