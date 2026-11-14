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
    # The host's own copy of this file runs; the uploaded release is only the build context.
    assert app["build"]["context"].startswith("${GPX_RELEASE:?")


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
    assert "IdentitiesOnly=yes" in workflow
    assert "SSH_KNOWN_HOSTS" in workflow
    assert 'git archive --format=tar.gz' in workflow
    assert '"$DEPLOY_SHA"' in workflow
    assert 'tar --exclude' not in workflow
    script = (ROOT / "deploy/deploy.sh").read_text()
    assert 'env_file="$root/.env"' in script
    assert "Production .env must have mode 600" in script
    assert 'readlink -f "$root/current"' in script
    assert "ssh-keyscan" not in workflow
    assert "StrictHostKeyChecking=no" not in workflow
    assert "head_sha" in workflow
    assert "gh api" in workflow
    assert workflow.count('gh api "repos/$GITHUB_REPOSITORY/git/ref/heads/main"') == 2


def test_ci_only_talks_to_the_deploy_gate() -> None:
    workflow = (ROOT / ".github/workflows/deploy.yml").read_text()
    assert "DEPLOY_GATE: /opt/gpx-route-generator/deploy/deploy-gate" in workflow
    assert '"$DEPLOY_GATE upload $DEPLOY_SHA"' in workflow
    assert '"$DEPLOY_GATE activate $DEPLOY_SHA"' in workflow
    # No remote shell commands: the pinned key can't run them, and nothing from the upload may run.
    for forbidden in ("mkdir -p", "tar -x", "bash '", "deploy/deploy.sh"):
        assert forbidden not in workflow


def test_host_scripts_never_run_release_files_or_sudo() -> None:
    script = (ROOT / "deploy/deploy.sh").read_text()
    assert "root=/opt/gpx-route-generator" in script
    assert 'compose_file="$root/deploy/compose.production.yml"' in script
    assert "$release/deploy" not in script
    assert "sudo" not in script
    gate = (ROOT / "deploy/deploy-gate.sh").read_text()
    assert 'exec bash "$ROOT/deploy/deploy.sh" "$RELEASE_ID"' in gate
    assert "$RELEASE_ID/" not in gate  # never runs anything from inside a release


def test_rollback_resolves_relative_current_symlink() -> None:
    script = (ROOT / "deploy/deploy.sh").read_text()
    assert 'readlink -f "$root/current"' in script
    assert 'up --detach --no-build --wait --wait-timeout 120' in script
    assert script.index('"${compose[@]}" build --pull') < script.index('"${compose[@]}" up --detach --remove-orphans')
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


@pytest.mark.parametrize("sha", ["not-a-sha", "a" * 39, "../" + "a" * 37, "A" * 40])
def test_activation_rejects_invalid_arguments_before_docker(sha) -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/deploy.sh"), sha],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "Invalid commit SHA" in result.stderr


@pytest.mark.parametrize("args,forced", [
    ([], None),
    (["upload", "abc"], None),
    (["activate", "../../etc"], None),
    (["upload", "a" * 40, "extra"], None),
    (["remove", "a" * 40], None),
    ([], "bash -c id"),
    ([], "upload " + "a" * 40 + "; id"),
    ([], "/opt/gpx-route-generator/deploy/deploy-gate activate $(id)"),
])
def test_gate_refuses_anything_but_upload_or_activate_of_a_sha(args, forced) -> None:
    env = {"PATH": "/usr/bin:/bin"}
    if forced is not None:
        env["SSH_ORIGINAL_COMMAND"] = forced
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/deploy-gate.sh"), *args],
        capture_output=True, text=True, check=False, env=env, stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 2


def test_setup_pins_the_ci_key_to_the_gate() -> None:
    setup = (ROOT / "deploy/setup-host.sh").read_text()
    assert 'restrict,command="%s/deploy/deploy-gate" %s' in setup
    assert '"$ROOT" "$CI_PUBLIC_KEY"' in setup
    assert 'sudo install -o root -g root -m 755 "$DEPLOY_DIR/deploy.sh" "$ROOT/deploy/deploy.sh"' in setup
    assert 'sudo install -o root -g root -m 644 "$DEPLOY_DIR/compose.production.yml"' in setup
