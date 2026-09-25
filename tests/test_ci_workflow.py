from __future__ import annotations

from pathlib import Path

import yaml


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml"


def _workflow() -> dict[str, object]:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps(job: dict[str, object]) -> list[dict[str, object]]:
    return job["steps"]  # type: ignore[return-value]


def test_quality_workflow_runs_required_gates() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]
    quality = jobs["quality"]
    quality_runs = [step.get("run", "") for step in _steps(quality)]
    docker_uses = [step.get("uses") for step in _steps(jobs["docker"])]

    assert "python -m pytest -q" in quality_runs
    assert "python -m compileall -q src tests benchmarks" in quality_runs
    assert "python -m pip check" in quality_runs
    assert "ruff check src tests benchmarks --select F --ignore F401" in quality_runs
    assert "docker/build-push-action@v6" in docker_uses
    assert jobs["docker"]["steps"][-1]["with"]["push"] is False


def test_quality_workflow_cancels_stale_branch_runs() -> None:
    workflow = _workflow()

    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert workflow["concurrency"]["group"]


def test_quality_workflow_has_bounded_jobs_and_read_only_permissions() -> None:
    workflow = _workflow()
    jobs = workflow["jobs"]

    assert workflow["permissions"] == {"contents": "read"}
    assert jobs["quality"]["timeout-minutes"] == 10
    assert jobs["docker"]["timeout-minutes"] == 15
    assert jobs["docker"]["needs"] == "quality"
