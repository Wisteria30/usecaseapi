"""Pull request contract check comment tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess

from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "write_contract_check_pr_comment.py"
)


def load_script() -> ModuleType:
    """Load the contract check comment script as a module."""
    spec = importlib.util.spec_from_file_location("write_contract_check_pr_comment", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_main_dry_run_prints_report_with_existing_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dry-run mode prints the report without calling GitHub."""
    script = load_script()
    report = tmp_path / "contract-check.md"
    report.write_text("<!-- usecaseapi-contract-check -->\n\n## UseCaseAPI Contract Check\n")

    exit_code = script.main(
        [
            "--report",
            str(report),
            "--repository",
            "Wisteria30/usecaseapi",
            "--pr-number",
            "1",
            "--dry-run",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.count("<!-- usecaseapi-contract-check -->") == 1
    assert "UseCaseAPI Contract Check" in output


def test_main_dry_run_prefixes_missing_marker(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reports without the marker are prefixed before printing."""
    script = load_script()
    report = tmp_path / "contract-check.md"
    report.write_text("## UseCaseAPI Contract Check\n")

    exit_code = script.main(
        [
            "--report",
            str(report),
            "--repository",
            "Wisteria30/usecaseapi",
            "--pr-number",
            "1",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out.startswith(
        "<!-- usecaseapi-contract-check -->\n\n## UseCaseAPI Contract Check"
    )


def test_upsert_comment_updates_existing_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing contract check comments are updated instead of duplicated."""
    script = load_script()
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert check
        if capture_output:
            assert text
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [{"id": 123, "body": "old <!-- usecaseapi-contract-check -->"}]
                ),
            )
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(script.subprocess, "run", fake_run)

    script.upsert_comment(repository="Wisteria30/usecaseapi", pr_number=1, body="new body")

    update_command = calls[-1]
    assert update_command[:4] == ["gh", "api", "--method", "PATCH"]
    assert "repos/Wisteria30/usecaseapi/issues/comments/123" in update_command
    assert "body=new body" in update_command


def test_upsert_comment_creates_missing_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing contract check comments are created."""
    script = load_script()
    calls: list[list[str]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert check
        if capture_output:
            assert text
            return subprocess.CompletedProcess(command, 0, stdout="[]")
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(script.subprocess, "run", fake_run)

    script.upsert_comment(repository="Wisteria30/usecaseapi", pr_number=1, body="new body")

    create_command = calls[-1]
    assert create_command[:4] == ["gh", "api", "--method", "POST"]
    assert "repos/Wisteria30/usecaseapi/issues/1/comments" in create_command
    assert "body=new body" in create_command


def test_upsert_comment_rejects_invalid_github_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The GitHub comments response must be a JSON list."""
    script = load_script()

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        assert check
        assert capture_output
        assert text
        return subprocess.CompletedProcess(command, 0, stdout="{}")

    monkeypatch.setattr(script.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="GitHub comments response must be a list"):
        script.upsert_comment(repository="Wisteria30/usecaseapi", pr_number=1, body="new body")
