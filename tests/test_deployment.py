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


def test_compose_uses_named_volume_for_render_data() -> None:
    compose = (ROOT / "docker-compose.yml").read_text()
    assert "app-data:/app/data" in compose
    assert "./data:/app/data" not in compose
    assert "\nvolumes:\n  app-data:\n    name: gpx-route-generator-data\n" in compose


def test_readme_backup_commands_use_explicit_compose_volume_name() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "-v gpx-route-generator-data:/data" in readme
    assert "-v app-data:/data" not in readme


def test_env_documents_limits_and_override() -> None:
    env_example = (ROOT / ".env.example").read_text()
    assert "MAX_UPLOAD_BYTES" in env_example
    assert "MAX_ROUTE_POINTS" in env_example
    assert "ALLOW_UNPROTECTED_RENDERING" in env_example


def test_readme_standalone_run_binds_loopback() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "-p 127.0.0.1:8000:8000" in readme
    assert "reverse proxy" in readme.lower()
    command = next(
        line for line in readme.splitlines() if line.startswith("docker run")
    )
    assert "8000:8000" in command
    assert "127.0.0.1:8000:8000" in command


def test_readme_requires_production_protection_settings() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "APP_ENV=production" in readme
    assert "RECAPTCHA_SITE_KEY" in readme
    assert "RECAPTCHA_SECRET_KEY" in readme
    assert "ALLOW_UNPROTECTED_RENDERING=true" in readme
    assert "unsafe" in readme.lower()
    assert "app-data" in readme


def test_env_example_production_requires_recaptcha() -> None:
    env_example = (ROOT / ".env.example").read_text()
    assert "APP_ENV=production" in env_example
    assert "RECAPTCHA_SITE_KEY" in env_example
    assert "RECAPTCHA_SECRET_KEY" in env_example
    assert "unsafe" in env_example.lower()
