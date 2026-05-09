"""Pull request coverage comment tests."""

from __future__ import annotations

import importlib.util
import json
import subprocess

from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "write_coverage_pr_comment.py"


def load_script() -> ModuleType:
    """Load the coverage comment script as a module."""
    spec = importlib.util.spec_from_file_location("write_coverage_pr_comment", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def coverage_report(*, statements: int, missing: int, percent: float, display: str) -> dict[str, object]:
    """Create a minimal coverage.py JSON report."""
    return {
        "totals": {
            "covered_lines": statements - missing,
            "num_statements": statements,
            "missing_lines": missing,
            "percent_covered": percent,
            "percent_covered_display": display,
        }
    }


def test_render_comment_includes_before_after_and_delta() -> None:
    """Rendered comments include coverage, statement, and missing-line deltas."""
    script = load_script()

    body = script.render_comment(
        coverage_report(statements=644, missing=0, percent=100.0, display="100"),
        coverage_report(statements=646, missing=0, percent=100.0, display="100"),
        python_version="3.13",
    )

    assert "<!-- usecaseapi-coverage-report -->" in body
    assert "| Total coverage | 100% | 100% | 0.00 pp |" in body
    assert "| Statements | 644 | 646 | +2 |" in body
    assert "| Missed statements | 0 | 0 | 0 |" in body


def test_main_dry_run_prints_comment(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Dry-run mode prints the comment without calling GitHub."""
    script = load_script()
    base = tmp_path / "base.json"
    head = tmp_path / "head.json"
    base.write_text(json.dumps(coverage_report(statements=10, missing=1, percent=90.0, display="90")))
    head.write_text(json.dumps(coverage_report(statements=10, missing=0, percent=100.0, display="100")))

    exit_code = script.main(
        [
            "--base",
            str(base),
            "--head",
            str(head),
            "--python-version",
            "3.13",
            "--repository",
            "Wisteria30/usecaseapi",
            "--pr-number",
            "1",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert "| Total coverage | 90% | 100% | +10.00 pp |" in capsys.readouterr().out


def test_upsert_comment_updates_existing_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Existing coverage comments are updated instead of duplicated."""
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
                stdout=json.dumps([{"id": 123, "body": "old <!-- usecaseapi-coverage-report -->"}]),
            )
        return subprocess.CompletedProcess(command, 0, stdout="")

    monkeypatch.setattr(script.subprocess, "run", fake_run)

    script.upsert_comment(repository="Wisteria30/usecaseapi", pr_number=1, body="new body")

    update_command = calls[-1]
    assert update_command[:4] == ["gh", "api", "--method", "PATCH"]
    assert "repos/Wisteria30/usecaseapi/issues/comments/123" in update_command
    assert "body=new body" in update_command


def test_upsert_comment_creates_missing_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing coverage comments are created."""
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
