"""GitHub workflow contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"
CI_WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"


def load_release_workflow() -> dict[str, Any]:
    """Load the release workflow as structured YAML."""
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return workflow


def load_ci_workflow() -> dict[str, Any]:
    """Load the CI workflow as structured YAML."""
    workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return workflow


def test_publish_job_creates_github_release_before_publishing_to_pypi() -> None:
    """Publishing creates a GitHub Release for the version tag before PyPI upload."""
    workflow = load_release_workflow()
    steps = workflow["jobs"]["publish"]["steps"]
    step_names = [step.get("name", "") for step in steps]

    tag_step_index = step_names.index("Create release tag")
    release_step_index = step_names.index("Create GitHub release")
    publish_step_index = step_names.index("Publish")

    assert tag_step_index < release_step_index < publish_step_index

    release_step = steps[release_step_index]
    assert release_step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert release_step["env"]["TAG_NAME"] == "${{ needs.check-version.outputs.tag_name }}"
    assert 'gh release create "$TAG_NAME"' in release_step["run"]
    assert "--verify-tag" in release_step["run"]
    assert "--generate-notes" in release_step["run"]


def test_ci_contract_check_job_uses_local_action_after_dependency_sync() -> None:
    """CI validates the example manifest through the local contract check action."""
    workflow = load_ci_workflow()
    job = workflow["jobs"]["contract-check"]
    steps = job["steps"]
    step_names = [step.get("name", "") for step in steps]

    sync_step_index = step_names.index("Sync dependencies")
    path_step_index = step_names.index("Add local tools to PATH")
    action_step_index = step_names.index("Check contracts")

    assert sync_step_index < path_step_index < action_step_index
    assert job["permissions"] == {"contents": "read"}

    sync_step = steps[sync_step_index]
    assert sync_step["run"] == "uv sync --frozen --extra dev"
    assert all(step.get("uses") != "actions/setup-python@v6" for step in steps)

    uv_step = next(step for step in steps if step.get("uses") == "astral-sh/setup-uv@v8.1.0")
    assert uv_step["with"]["python-version"] == "3.13"

    path_step = steps[path_step_index]
    assert path_step["run"] == 'echo "$PWD/.venv/bin" >> "$GITHUB_PATH"'

    action_step = steps[action_step_index]
    assert action_step["uses"] == "./actions/contract-check"
    assert action_step["env"]["PYTHONPATH"] == "examples/basic/src"
    assert action_step["with"] == {
        "comment-on-pr": "false",
        "manifest": "examples/basic/usecaseapi.yaml",
        "target": "composition:usecases",
    }


def test_ci_does_not_use_separate_python_setup_action() -> None:
    """CI delegates Python setup to setup-uv instead of a separate Python action."""
    workflow = load_ci_workflow()

    for job in workflow["jobs"].values():
        steps = job["steps"]
        assert all(step.get("uses") != "actions/setup-python@v6" for step in steps)


@pytest.mark.parametrize(
    ("job_name", "expected_python_version"),
    [
        ("test", "${{ matrix.python-version }}"),
        ("coverage-report", "3.13"),
        ("contract-check", "3.13"),
        ("quality", "3.13"),
        ("package", "3.13"),
    ],
)
def test_ci_uses_setup_uv_for_python_versions(
    job_name: str,
    expected_python_version: str,
) -> None:
    """CI declares Python versions through setup-uv for each job."""
    # Given
    workflow = load_ci_workflow()
    steps = workflow["jobs"][job_name]["steps"]

    # When
    uv_step = next(step for step in steps if step.get("uses") == "astral-sh/setup-uv@v8.1.0")

    # Then
    assert uv_step["with"]["python-version"] == expected_python_version
