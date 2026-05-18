"""Contract check GitHub Action metadata tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

ACTION_PATH = Path(__file__).resolve().parents[1] / "actions" / "contract-check" / "action.yml"


def load_action() -> dict[str, Any]:
    """Load the composite action metadata."""
    return cast(dict[str, Any], yaml.safe_load(ACTION_PATH.read_text()))


def step_by_name(action: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a composite action step by display name."""
    steps = cast(list[dict[str, Any]], cast(dict[str, Any], action["runs"])["steps"])
    return next(step for step in steps if step["name"] == name)


def test_contract_check_action_requires_target_and_sets_defaults() -> None:
    """The action exposes the required target input and documented defaults."""
    action = load_action()
    inputs = cast(dict[str, dict[str, Any]], action["inputs"])

    assert inputs["target"]["required"] is True
    assert inputs["manifest"]["required"] is False
    assert inputs["manifest"]["default"] == "usecaseapi.yaml"
    assert inputs["artifact-name"]["required"] is False
    assert inputs["artifact-name"]["default"] == "usecaseapi-contract-check"
    assert inputs["comment-on-pr"]["required"] is False
    assert inputs["comment-on-pr"]["default"] == "false"
    assert action["runs"]["using"] == "composite"


def test_contract_check_action_has_required_steps() -> None:
    """The action keeps the expected composite step order."""
    action = load_action()
    steps = cast(list[dict[str, Any]], cast(dict[str, Any], action["runs"])["steps"])
    step_names = [step["name"] for step in steps]

    assert step_names == [
        "Prepare output directory",
        "Check out base manifest",
        "Run UseCaseAPI contract check",
        "Write step summary",
        "Comment on pull request",
        "Upload contract check artifacts",
    ]


def test_contract_check_action_checks_out_pull_request_base() -> None:
    """Pull requests check out the base commit into the report directory."""
    action = load_action()
    step = step_by_name(action, "Check out base manifest")

    assert step["if"] == "github.event_name == 'pull_request'"
    assert step["uses"] == "actions/checkout@v6"
    assert step["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert step["with"]["path"] == "build/usecaseapi-contract-check/base-checkout"
    assert step["with"]["persist-credentials"] is False


def test_contract_check_action_runs_manifest_ci_and_captures_reports() -> None:
    """The action runs manifest ci with head and optional base report paths."""
    action = load_action()
    step = step_by_name(action, "Run UseCaseAPI contract check")
    script = cast(str, step["run"])

    assert step["shell"] == "bash"
    assert step["env"]["INPUT_MANIFEST"] == "${{ inputs.manifest }}"
    assert step["env"]["INPUT_TARGET"] == "${{ inputs.target }}"
    assert "set -euo pipefail" in script
    assert "BASE_ARG=()" in script
    assert "${{ inputs.manifest }}" not in script
    assert "${{ inputs.target }}" not in script
    assert 'BASE_ARG=(--base-manifest "$BASE_PATH")' in script
    assert 'BASE_PATH="build/usecaseapi-contract-check/base-checkout/$INPUT_MANIFEST"' in script
    assert 'cp -- "$BASE_PATH" build/usecaseapi-contract-check/base.usecaseapi.yaml' in script
    assert 'cp -- "$INPUT_MANIFEST" build/usecaseapi-contract-check/head.usecaseapi.yaml' in script
    assert "usecaseapi manifest ci \\" in script
    assert '--target "$INPUT_TARGET"' in script
    assert '--manifest "$INPUT_MANIFEST"' in script
    assert '"${BASE_ARG[@]}" \\' in script
    assert "--summary build/usecaseapi-contract-check/contract-check.md" in script
    assert "--json build/usecaseapi-contract-check/contract-check.json" in script


def test_contract_check_action_writes_summary_comments_and_uploads_artifact() -> None:
    """The action publishes the Markdown report and uploads the report directory."""
    action = load_action()

    summary = step_by_name(action, "Write step summary")
    assert summary["if"] == "always()"
    assert '>> "$GITHUB_STEP_SUMMARY"' in cast(str, summary["run"])

    comment = step_by_name(action, "Comment on pull request")
    comment_script = cast(str, comment["run"])
    assert comment["if"] == (
        "always() && github.event_name == 'pull_request' && inputs.comment-on-pr == 'true'"
    )
    assert comment["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert 'python "$GITHUB_ACTION_PATH/../../scripts/write_contract_check_pr_comment.py" \\' in (
        comment_script
    )
    assert "--report build/usecaseapi-contract-check/contract-check.md" in comment_script
    assert '--repository "${{ github.repository }}"' in comment_script
    assert '--pr-number "${{ github.event.pull_request.number }}"' in comment_script

    artifact = step_by_name(action, "Upload contract check artifacts")
    assert artifact["if"] == "always()"
    assert artifact["uses"] == "actions/upload-artifact@v7.0.1"
    assert artifact["with"]["name"] == "${{ inputs.artifact-name }}"
    assert artifact["with"]["path"] == "build/usecaseapi-contract-check"
    assert artifact["with"]["if-no-files-found"] == "error"
