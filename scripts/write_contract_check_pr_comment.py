"""Write or update a pull request comment with UseCaseAPI contract check results."""

from __future__ import annotations

import argparse
import json
import subprocess

from collections.abc import Sequence
from pathlib import Path

COMMENT_MARKER = "<!-- usecaseapi-contract-check -->"


def main(argv: Sequence[str] | None = None) -> int:
    """Read a contract check report and optionally publish it to GitHub."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    body = _read_report(args.report)
    if args.dry_run:
        print(body)
        return 0

    upsert_comment(
        repository=args.repository,
        pr_number=args.pr_number,
        body=body,
    )
    return 0


def upsert_comment(*, repository: str, pr_number: int, body: str) -> None:
    """Create or update the PR contract check comment."""
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


def _read_report(path: Path) -> str:
    body = path.read_text()
    if COMMENT_MARKER in body:
        return body
    return COMMENT_MARKER + "\n\n" + body


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


if __name__ == "__main__":
    raise SystemExit(main())
