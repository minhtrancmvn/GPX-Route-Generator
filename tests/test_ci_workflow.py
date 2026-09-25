from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "quality.yml"


def test_quality_workflow_runs_required_gates() -> None:
    workflow = WORKFLOW.read_text()

    assert "python -m pytest -q" in workflow
    assert "python -m compileall -q src tests benchmarks" in workflow
    assert "python -m pip check" in workflow
    assert "ruff check src tests benchmarks --select F --ignore F401" in workflow
    assert "docker/build-push-action@v6" in workflow
    assert "push: false" in workflow


def test_quality_workflow_cancels_stale_branch_runs() -> None:
    workflow = WORKFLOW.read_text()

    assert "concurrency:" in workflow
    assert "cancel-in-progress: true" in workflow


def test_quality_workflow_has_bounded_jobs_and_read_only_permissions() -> None:
    workflow = WORKFLOW.read_text()

    assert workflow.count("timeout-minutes:") == 2
    assert "permissions:\n  contents: read" in workflow
