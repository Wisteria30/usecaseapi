"""Write a Markdown coverage summary for GitHub Actions."""

from __future__ import annotations

import json
import os

from pathlib import Path


def main() -> int:
    """Render coverage.json into a GitHub step summary or stdout."""
    report = json.loads(Path("coverage.json").read_text())
    total = report["totals"]["percent_covered_display"]
    python_version = os.environ.get("PYTHON_VERSION", "local")
    content = _render_summary(report, python_version=python_version, total=total)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path is None:
        print(content, end="")
        return 0
    with Path(summary_path).open("a") as summary:
        summary.write(content)
    return 0


def _render_summary(report: dict[str, object], *, python_version: str, total: str) -> str:
    lines = [
        f"### Coverage for Python {python_version}",
        "",
        f"Total: **{total}%**",
        "",
        "| File | Coverage | Missing |",
        "| --- | ---: | --- |",
    ]
    files = report["files"]
    assert isinstance(files, dict)
    for filename, details in sorted(files.items()):
        assert isinstance(details, dict)
        summary = details["summary"]
        missing_lines = details["missing_lines"]
        assert isinstance(summary, dict)
        assert isinstance(missing_lines, list)
        coverage = summary["percent_covered_display"]
        missing = ", ".join(str(line) for line in missing_lines) or "-"
        lines.append(f"| `{filename}` | {coverage}% | {missing} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
