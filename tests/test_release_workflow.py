"""Release workflow contract tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "release.yml"


def load_release_workflow() -> dict[str, Any]:
    """Load the release workflow as structured YAML."""
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
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
