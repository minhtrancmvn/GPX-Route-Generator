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
