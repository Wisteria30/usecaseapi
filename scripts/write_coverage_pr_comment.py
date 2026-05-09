"""Write or update a pull request comment with coverage before/after."""

from __future__ import annotations

import argparse
import json
import subprocess

from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

COMMENT_MARKER = "<!-- usecaseapi-coverage-report -->"


class CoverageTotals(TypedDict):
    """Coverage totals extracted from coverage.py JSON output."""

    covered_lines: int
    num_statements: int
    missing_lines: int
    percent_covered: float
    percent_covered_display: str


class CoverageReport(TypedDict):
    """Coverage report fields used for pull request comments."""

    totals: CoverageTotals


def main(argv: Sequence[str] | None = None) -> int:
    """Render a coverage comparison and optionally publish it to GitHub."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--head", type=Path, required=True)
    parser.add_argument("--python-version", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    base_report = _load_report(args.base)
    head_report = _load_report(args.head)
    body = render_comment(
        base_report,
        head_report,
        python_version=args.python_version,
    )

    if args.dry_run:
        print(body)
        return 0

    upsert_comment(
        repository=args.repository,
        pr_number=args.pr_number,
        body=body,
    )
    return 0


def render_comment(
    base_report: CoverageReport,
    head_report: CoverageReport,
    *,
    python_version: str,
) -> str:
    """Render a Markdown coverage before/after comparison."""
    base = base_report["totals"]
    head = head_report["totals"]
    delta = head["percent_covered"] - base["percent_covered"]
    statements_delta = head["num_statements"] - base["num_statements"]
    missing_delta = head["missing_lines"] - base["missing_lines"]

    return "\n".join(
        [
            COMMENT_MARKER,
            "## Coverage",
            "",
            f"Python: `{python_version}`",
            "",
            "| Metric | Base | PR | Delta |",
            "| --- | ---: | ---: | ---: |",
            (
                "| Total coverage | "
                f"{base['percent_covered_display']}% | "
                f"{head['percent_covered_display']}% | "
                f"{_format_percent_delta(delta)} |"
            ),
            (
                "| Statements | "
                f"{base['num_statements']} | "
                f"{head['num_statements']} | "
                f"{_format_integer_delta(statements_delta)} |"
            ),
            (
                "| Missed statements | "
                f"{base['missing_lines']} | "
                f"{head['missing_lines']} | "
                f"{_format_integer_delta(missing_delta)} |"
            ),
            "",
            "This comment is updated automatically by CI.",
            "",
        ]
    )


def upsert_comment(*, repository: str, pr_number: int, body: str) -> None:
    """Create or update the PR coverage comment."""
    comment_id = _find_existing_comment_id(repository=repository, pr_number=pr_number)
    if comment_id is None:
        _run_gh_api(
            "POST",
            f"repos/{repository}/issues/{pr_number}/comments",
            body=body,
        )
        return
    _run_gh_api(
        "PATCH",
        f"repos/{repository}/issues/comments/{comment_id}",
        body=body,
    )


def _load_report(path: Path) -> CoverageReport:
    report = json.loads(path.read_text())
    if not isinstance(report, dict):
        raise ValueError(f"coverage report must be an object: {path}")
    totals = report.get("totals")
    if not isinstance(totals, dict):
        raise ValueError(f"coverage report is missing totals: {path}")
    return cast(CoverageReport, report)


def _find_existing_comment_id(*, repository: str, pr_number: int) -> int | None:
    completed = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repository}/issues/{pr_number}/comments",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    comments = json.loads(completed.stdout)
    if not isinstance(comments, list):
        raise ValueError("GitHub comments response must be a list")
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        body = comment.get("body")
        comment_id = comment.get("id")
        if isinstance(body, str) and COMMENT_MARKER in body and isinstance(comment_id, int):
            return comment_id
    return None


def _run_gh_api(method: str, endpoint: str, *, body: str) -> None:
    subprocess.run(
        [
            "gh",
            "api",
            "--method",
            method,
            endpoint,
            "-f",
            f"body={body}",
        ],
        check=True,
    )


def _format_percent_delta(value: float) -> str:
    if value > 0:
        return f"+{value:.2f} pp"
    if value < 0:
        return f"{value:.2f} pp"
    return "0.00 pp"


def _format_integer_delta(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
