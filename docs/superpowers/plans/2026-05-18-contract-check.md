# Contract Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable CI contract check that validates committed `usecaseapi.yaml`, checks synchronization with code, and rejects changes or removals to existing usecase versions.

**Architecture:** Extend the existing manifest module and CLI rather than creating a separate contract subsystem. Add a small report model for immutable-version guard results, a `manifest ci` orchestration command, a PR comment script following the existing coverage comment pattern, and a composite GitHub Action wrapper.

**Tech Stack:** Python 3.12+, Typer, PyYAML, GitHub Actions composite actions, `gh` CLI for PR comments, existing `UseCaseAPI` manifest APIs.

---

## File Structure

- Modify `src/usecaseapi/manifest.py`: immutable-version guard, report rendering, and CI orchestration helpers.
- Modify `src/usecaseapi/cli.py`: add `usecaseapi manifest guard` and `usecaseapi manifest ci`.
- Create `scripts/write_contract_check_pr_comment.py`: update one PR comment from a Markdown report.
- Create `actions/contract-check/action.yml`: public composite action.
- Modify `.github/workflows/ci.yml`: run the new action against `examples/basic`.
- Modify `docs/manifest.md`: document the contract check workflow.
- Create or modify tests:
  - `tests/test_manifest.py`
  - `tests/test_contract_check_pr_comment.py`
  - `tests/test_contract_check_action.py`

---

### Task 1: Immutable Manifest Guard Model

**Files:**
- Modify: `src/usecaseapi/manifest.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write failing tests for additions, removals, and changes**

Add tests near the existing manifest diff tests:

```python
def test_manifest_guard_allows_new_usecase_version() -> None:
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = copy.deepcopy(base)
    paths = cast(dict[str, object], head["paths"])
    existing_path = next(iter(paths))
    new_path = existing_path.replace("/v1/", "/v2/")
    new_operation = copy.deepcopy(paths[existing_path])
    post = cast(dict[str, object], cast(dict[str, object], new_operation)["post"])
    extension = cast(dict[str, object], post["x-usecaseapi"])
    extension["version"] = 2
    extension["key"] = str(extension["key"]).replace("@v1", "@v2")
    paths[new_path] = new_operation

    report = guard_manifests(base, head)

    assert report.failed is False
    assert "commerce." in report.added[0]
    assert report.changed == ()
    assert report.removed == ()
```

```python
def test_manifest_guard_rejects_removed_existing_version() -> None:
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = copy.deepcopy(base)
    paths = cast(dict[str, object], head["paths"])
    removed_path = next(iter(paths))
    del paths[removed_path]

    report = guard_manifests(base, head)

    assert report.failed is True
    assert report.removed
    assert report.changed == ()
```

```python
def test_manifest_guard_rejects_changed_existing_version() -> None:
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = copy.deepcopy(base)
    paths = cast(dict[str, object], head["paths"])
    operation = cast(dict[str, object], cast(dict[str, object], next(iter(paths.values())))["post"])
    operation["summary"] = "changed summary"

    report = guard_manifests(base, head)

    assert report.failed is True
    assert report.changed
    assert report.removed == ()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_manifest.py::test_manifest_guard_allows_new_usecase_version tests/test_manifest.py::test_manifest_guard_rejects_removed_existing_version tests/test_manifest.py::test_manifest_guard_rejects_changed_existing_version -q
```

Expected: import/name failure because `guard_manifests` does not exist.

- [ ] **Step 3: Add guard report dataclass and helpers**

Add to `src/usecaseapi/manifest.py` near `ManifestDiff`:

```python
@dataclass(frozen=True, slots=True)
class ManifestGuardReport:
    """Immutable-version guard result for two UseCaseAPI manifests."""

    removed: tuple[str, ...]
    changed: tuple[str, ...]
    added: tuple[str, ...]

    @property
    def failed(self) -> bool:
        """Whether immutable contract versions were removed or changed."""
        return bool(self.removed or self.changed)

    def to_dict(self) -> dict[str, list[str] | bool]:
        """Return a JSON-friendly representation."""
        return {
            "failed": self.failed,
            "removed": list(self.removed),
            "changed": list(self.changed),
            "added": list(self.added),
        }
```

Add:

```python
def guard_manifests(base: Mapping[str, Any], head: Mapping[str, Any]) -> ManifestGuardReport:
    """Reject removals or changes to existing usecase name/version contracts."""
    validate_manifest(base)
    validate_manifest(head)
    base_cases = immutable_usecase_index(base)
    head_cases = immutable_usecase_index(head)
    removed = tuple(sorted(set(base_cases) - set(head_cases)))
    added = tuple(sorted(set(head_cases) - set(base_cases)))
    changed = tuple(
        key
        for key in sorted(set(base_cases) & set(head_cases))
        if base_cases[key] != head_cases[key]
    )
    return ManifestGuardReport(removed=removed, changed=changed, added=added)
```

Add:

```python
def immutable_usecase_index(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return normalized operation contracts keyed by name and version."""
    result: dict[str, dict[str, Any]] = {}
    paths = required_mapping(manifest, "paths")
    for path, path_item in paths.items():
        if not isinstance(path_item, Mapping):
            continue
        post = path_item.get("post")
        if not isinstance(post, Mapping):
            continue
        extension = required_mapping(post, "x-usecaseapi")
        name = required_string(extension, "name")
        version = required_int(extension, "version")
        identity = f"{name}@v{version}"
        result[identity] = normalize_immutable_operation(
            manifest=manifest,
            path=str(path),
            operation=post,
        )
    return result
```

Add:

```python
def normalize_immutable_operation(
    *,
    manifest: Mapping[str, Any],
    path: str,
    operation: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the operation data that must not change for an existing version."""
    return sort_json_like(
        {
            "path": path,
            "method": "post",
            "operation": operation,
            "components": required_mapping(manifest, "components"),
            "x-usecaseapi-errors": (
                required_mapping(
                    required_mapping(required_mapping(manifest, "x-usecaseapi"), "components"),
                    "errors",
                )
                if isinstance(required_mapping(manifest, "x-usecaseapi").get("components"), Mapping)
                else {}
            ),
        }
    )
```

Add:

```python
def sort_json_like(value: Any) -> Any:
    """Recursively sort JSON-like values for stable semantic comparison."""
    if isinstance(value, Mapping):
        return {str(key): sort_json_like(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [sort_json_like(item) for item in value]
    if isinstance(value, tuple):
        return [sort_json_like(item) for item in value]
    return value
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_manifest.py::test_manifest_guard_allows_new_usecase_version tests/test_manifest.py::test_manifest_guard_rejects_removed_existing_version tests/test_manifest.py::test_manifest_guard_rejects_changed_existing_version -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/usecaseapi/manifest.py tests/test_manifest.py
git commit -m "feat: add immutable manifest guard"
```

---

### Task 2: Manifest Guard CLI

**Files:**
- Modify: `src/usecaseapi/cli.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write failing CLI test**

Add:

```python
def test_manifest_guard_cli_fails_for_changed_existing_version(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    head_path = tmp_path / "head.yaml"
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = copy.deepcopy(base)
    paths = cast(dict[str, object], head["paths"])
    operation = cast(dict[str, object], cast(dict[str, object], next(iter(paths.values())))["post"])
    operation["summary"] = "changed summary"
    dump_manifest(base, base_path)
    dump_manifest(head, head_path)

    assert main(["manifest", "guard", str(base_path), str(head_path)]) == 1
```

Add a passing CLI test:

```python
def test_manifest_guard_cli_passes_for_identical_manifests(tmp_path: Path) -> None:
    base_path = tmp_path / "base.yaml"
    head_path = tmp_path / "head.yaml"
    manifest = load_manifest("examples/basic/usecaseapi.yaml")
    dump_manifest(manifest, base_path)
    dump_manifest(manifest, head_path)

    assert main(["manifest", "guard", str(base_path), str(head_path)]) == 0
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_manifest.py::test_manifest_guard_cli_fails_for_changed_existing_version tests/test_manifest.py::test_manifest_guard_cli_passes_for_identical_manifests -q
```

Expected: fail because `manifest guard` command does not exist.

- [ ] **Step 3: Add CLI command**

Import `guard_manifests` from `.manifest`.

Add to `src/usecaseapi/cli.py`:

```python
@manifest_app.command("guard")
def manifest_guard(
    base: Annotated[Path, typer.Argument(help="Base usecaseapi.yaml path")],
    head: Annotated[Path, typer.Argument(help="Head usecaseapi.yaml path")],
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON output")] = False,
) -> None:
    """Reject changes to existing usecase contract versions."""
    report = guard_manifests(load_manifest(base), load_manifest(head))
    if json_output:
        typer.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        echo_contract_guard(report)
    if report.failed:
        raise typer.Exit(1)
```

Add:

```python
def echo_contract_guard(report: ManifestGuardReport) -> None:
    """Print immutable-version guard sections in the CLI format."""
    for label, items in (
        ("Removed", report.removed),
        ("Changed", report.changed),
        ("Additions", report.added),
    ):
        typer.echo(label + ":")
        if items:
            for item in items:
                typer.echo(f"  - {item}")
        else:
            typer.echo("  - none")
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/test_manifest.py::test_manifest_guard_cli_fails_for_changed_existing_version tests/test_manifest.py::test_manifest_guard_cli_passes_for_identical_manifests -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/usecaseapi/cli.py tests/test_manifest.py
git commit -m "feat: add manifest guard cli"
```

---

### Task 3: Contract Check Report Rendering And CI Command

**Files:**
- Modify: `src/usecaseapi/manifest.py`
- Modify: `src/usecaseapi/cli.py`
- Test: `tests/test_manifest.py`

- [ ] **Step 1: Write failing tests for `manifest ci`**

Add:

```python
def test_manifest_ci_writes_reports_for_valid_example(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from usecaseapi.cli import main

    summary = tmp_path / "contract-check.md"
    json_report = tmp_path / "contract-check.json"
    monkeypatch.chdir("examples/basic")

    exit_code = main(
        [
            "manifest",
            "ci",
            "--target",
            "composition:usecases",
            "--manifest",
            "usecaseapi.yaml",
            "--summary",
            str(summary),
            "--json",
            str(json_report),
        ]
    )

    assert exit_code == 0
    assert "Status: Passed" in summary.read_text()
    assert json.loads(json_report.read_text())["status"] == "passed"
```

Add failure test:

```python
def test_manifest_ci_fails_when_base_contract_changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from usecaseapi.cli import main

    base_path = tmp_path / "base.yaml"
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = copy.deepcopy(base)
    paths = cast(dict[str, object], base["paths"])
    operation = cast(dict[str, object], cast(dict[str, object], next(iter(paths.values())))["post"])
    operation["summary"] = "old summary"
    dump_manifest(base, base_path)
    head_path = tmp_path / "usecaseapi.yaml"
    dump_manifest(head, head_path)
    monkeypatch.chdir("examples/basic")

    exit_code = main(
        [
            "manifest",
            "ci",
            "--target",
            "composition:usecases",
            "--manifest",
            str(head_path),
            "--base-manifest",
            str(base_path),
        ]
    )

    assert exit_code == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_manifest.py::test_manifest_ci_writes_reports_for_valid_example tests/test_manifest.py::test_manifest_ci_fails_when_base_contract_changed -q
```

Expected: fail because `manifest ci` does not exist.

- [ ] **Step 3: Add report dataclass and renderers**

Add to `src/usecaseapi/manifest.py`:

```python
@dataclass(frozen=True, slots=True)
class ContractCheckReport:
    """Result of validating one committed UseCaseAPI manifest."""

    manifest: str
    target: str
    manifest_valid: bool
    synchronized: bool
    guard: ManifestGuardReport | None
    errors: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        """Whether the contract check should fail CI."""
        return bool(
            self.errors
            or not self.manifest_valid
            or not self.synchronized
            or (self.guard is not None and self.guard.failed)
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly report."""
        return {
            "status": "failed" if self.failed else "passed",
            "manifest": self.manifest,
            "target": self.target,
            "validation": {
                "manifest": "passed" if self.manifest_valid else "failed",
                "sync": "passed" if self.synchronized else "failed",
            },
            "guard": self.guard.to_dict() if self.guard is not None else None,
            "errors": list(self.errors),
        }
```

Add:

```python
def render_contract_check_markdown(report: ContractCheckReport) -> str:
    """Render a Markdown contract check report."""
    lines = [
        "<!-- usecaseapi-contract-check -->",
        "",
        "## UseCaseAPI Contract Check",
        "",
        f"Status: {'Failed' if report.failed else 'Passed'}",
        "",
        f"Manifest: `{report.manifest}`",
        f"Target: `{report.target}`",
        "",
        "Failures:",
    ]
    failures = list(report.errors)
    if report.guard is not None:
        failures.extend(
            f"`{item}` was removed." for item in report.guard.removed
        )
        failures.extend(
            f"`{item}` changed. Existing contract versions are immutable."
            for item in report.guard.changed
        )
    if failures:
        lines.extend(f"- {item}" for item in failures)
    else:
        lines.append("- none")
    additions = report.guard.added if report.guard is not None else ()
    lines.extend(["", "Additions:"])
    lines.extend((f"- `{item}`" for item in additions),)
    if not additions:
        lines.append("- none")
    lines.extend(
        [
            "",
            "Validation:",
            f"- Manifest: {'passed' if report.manifest_valid else 'failed'}",
            f"- Code sync: {'passed' if report.synchronized else 'failed'}",
            "",
        ]
    )
    return "\n".join(lines)
```

When implementing, fix the `lines.extend((generator,),)` shape to use a normal
loop if mypy or tests reject it:

```python
for item in additions:
    lines.append(f"- `{item}`")
```

- [ ] **Step 4: Add `manifest ci` command**

Add to `src/usecaseapi/cli.py`:

```python
@manifest_app.command("ci")
def manifest_ci(
    target: Annotated[str, typer.Option("--target", help="Import path like 'composition:usecases'")],
    manifest: Annotated[Path, typer.Option("--manifest", help="Head usecaseapi.yaml path")] = Path("usecaseapi.yaml"),
    base_manifest: Annotated[Path | None, typer.Option("--base-manifest")] = None,
    summary: Annotated[Path | None, typer.Option("--summary")] = None,
    json_report: Annotated[Path | None, typer.Option("--json")] = None,
) -> None:
    """Validate committed manifest, check code sync, and guard existing versions."""
    report = run_contract_check(
        target=target,
        manifest_path=manifest,
        base_manifest_path=base_manifest,
    )
    markdown = render_contract_check_markdown(report)
    typer.echo(markdown)
    if summary is not None:
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(markdown)
    if json_report is not None:
        json_report.parent.mkdir(parents=True, exist_ok=True)
        json_report.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if report.failed:
        raise typer.Exit(1)
```

Add `run_contract_check()` either in `manifest.py` or `cli.py`. Prefer
`manifest.py` if it has no CLI dependencies:

```python
def run_contract_check(
    *,
    target: str,
    manifest_path: Path,
    base_manifest_path: Path | None,
    api: UseCaseAPI[Any],
) -> ContractCheckReport:
    """Validate one committed manifest against code and an optional base manifest."""
```

If keeping `load_api()` in CLI, the CLI can load the API and pass it to a
manifest-layer helper.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/test_manifest.py::test_manifest_ci_writes_reports_for_valid_example tests/test_manifest.py::test_manifest_ci_fails_when_base_contract_changed -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/usecaseapi/manifest.py src/usecaseapi/cli.py tests/test_manifest.py
git commit -m "feat: add manifest ci command"
```

---

### Task 4: PR Comment Script

**Files:**
- Create: `scripts/write_contract_check_pr_comment.py`
- Create: `tests/test_contract_check_pr_comment.py`

- [ ] **Step 1: Write tests copied from coverage comment shape**

Create `tests/test_contract_check_pr_comment.py`:

```python
"""Pull request contract check comment tests."""

from __future__ import annotations

import importlib.util
import subprocess

from pathlib import Path
from types import ModuleType

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "write_contract_check_pr_comment.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("write_contract_check_pr_comment", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_main_dry_run_prints_report(tmp_path: Path, capsys) -> None:
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

    assert exit_code == 0
    assert "UseCaseAPI Contract Check" in capsys.readouterr().out
```

Add update/create tests by mirroring `tests/test_coverage_pr_comment.py` and
changing the marker to `<!-- usecaseapi-contract-check -->`.

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_contract_check_pr_comment.py -q
```

Expected: fail because script does not exist.

- [ ] **Step 3: Create script**

Create `scripts/write_contract_check_pr_comment.py`:

```python
"""Write or update a pull request comment with UseCaseAPI contract check results."""

from __future__ import annotations

import argparse
import json
import subprocess

from collections.abc import Sequence
from pathlib import Path

COMMENT_MARKER = "<!-- usecaseapi-contract-check -->"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    body = args.report.read_text()
    if COMMENT_MARKER not in body:
        body = COMMENT_MARKER + "\n\n" + body

    if args.dry_run:
        print(body)
        return 0

    upsert_comment(repository=args.repository, pr_number=args.pr_number, body=body)
    return 0


def upsert_comment(*, repository: str, pr_number: int, body: str) -> None:
    comment_id = _find_existing_comment_id(repository=repository, pr_number=pr_number)
    if comment_id is None:
        _run_gh_api("POST", f"repos/{repository}/issues/{pr_number}/comments", body=body)
        return
    _run_gh_api("PATCH", f"repos/{repository}/issues/comments/{comment_id}", body=body)


def _find_existing_comment_id(*, repository: str, pr_number: int) -> int | None:
    completed = subprocess.run(
        ["gh", "api", f"repos/{repository}/issues/{pr_number}/comments"],
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
    subprocess.run(["gh", "api", "--method", method, endpoint, "-f", f"body={body}"], check=True)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run pytest tests/test_contract_check_pr_comment.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/write_contract_check_pr_comment.py tests/test_contract_check_pr_comment.py
git commit -m "feat: add contract check pr comment script"
```

---

### Task 5: Composite Action

**Files:**
- Create: `actions/contract-check/action.yml`
- Create: `tests/test_contract_check_action.py`

- [ ] **Step 1: Write action metadata test**

Create `tests/test_contract_check_action.py`:

```python
"""Contract check GitHub Action metadata tests."""

from __future__ import annotations

from pathlib import Path

import yaml

ACTION_PATH = Path(__file__).resolve().parents[1] / "actions" / "contract-check" / "action.yml"


def test_contract_check_action_requires_target_and_defaults_manifest() -> None:
    action = yaml.safe_load(ACTION_PATH.read_text())

    assert action["inputs"]["target"]["required"] is True
    assert action["inputs"]["manifest"]["default"] == "usecaseapi.yaml"
    assert action["runs"]["using"] == "composite"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/test_contract_check_action.py -q
```

Expected: fail because action file does not exist.

- [ ] **Step 3: Create action**

Create `actions/contract-check/action.yml`:

```yaml
name: UseCaseAPI Contract Check
description: Validate committed usecaseapi.yaml, check code sync, and guard existing versions.
inputs:
  target:
    description: Python import path for the UseCaseAPI instance, such as composition:usecases.
    required: true
  manifest:
    description: Path to the committed UseCaseAPI manifest.
    required: false
    default: usecaseapi.yaml
  artifact-name:
    description: Name for uploaded contract check artifacts.
    required: false
    default: usecaseapi-contract-check
runs:
  using: composite
  steps:
    - name: Prepare output directory
      shell: bash
      run: mkdir -p build/usecaseapi-contract-check
    - name: Check out base manifest
      if: github.event_name == 'pull_request'
      uses: actions/checkout@v6
      with:
        ref: ${{ github.event.pull_request.base.sha }}
        path: build/usecaseapi-contract-check/base-checkout
        persist-credentials: false
    - name: Run UseCaseAPI contract check
      shell: bash
      run: |
        set -euo pipefail
        BASE_ARG=()
        if [ "${{ github.event_name }}" = "pull_request" ]; then
          BASE_PATH="build/usecaseapi-contract-check/base-checkout/${{ inputs.manifest }}"
          if [ -f "$BASE_PATH" ]; then
            cp "$BASE_PATH" build/usecaseapi-contract-check/base.usecaseapi.yaml
            BASE_ARG=(--base-manifest "$BASE_PATH")
          fi
        fi
        cp "${{ inputs.manifest }}" build/usecaseapi-contract-check/head.usecaseapi.yaml
        usecaseapi manifest ci \
          --target "${{ inputs.target }}" \
          --manifest "${{ inputs.manifest }}" \
          "${BASE_ARG[@]}" \
          --summary build/usecaseapi-contract-check/contract-check.md \
          --json build/usecaseapi-contract-check/contract-check.json
    - name: Write step summary
      if: always()
      shell: bash
      run: |
        if [ -f build/usecaseapi-contract-check/contract-check.md ]; then
          cat build/usecaseapi-contract-check/contract-check.md >> "$GITHUB_STEP_SUMMARY"
        fi
    - name: Comment on pull request
      if: always() && github.event_name == 'pull_request'
      shell: bash
      run: |
        if [ -f build/usecaseapi-contract-check/contract-check.md ]; then
          python scripts/write_contract_check_pr_comment.py \
            --report build/usecaseapi-contract-check/contract-check.md \
            --repository "${{ github.repository }}" \
            --pr-number "${{ github.event.pull_request.number }}"
        fi
    - name: Upload contract check artifacts
      if: always()
      uses: actions/upload-artifact@v7.0.1
      with:
        name: ${{ inputs.artifact-name }}
        path: build/usecaseapi-contract-check
        if-no-files-found: error
        retention-days: 7
```

- [ ] **Step 4: Run action metadata test**

Run:

```bash
uv run pytest tests/test_contract_check_action.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add actions/contract-check/action.yml tests/test_contract_check_action.py
git commit -m "feat: add contract check github action"
```

---

### Task 6: Repository CI Integration

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_contract_check_action.py`

- [ ] **Step 1: Write workflow test**

Append to `tests/test_contract_check_action.py`:

```python
def test_ci_workflow_runs_contract_check_action_for_basic_example() -> None:
    workflow_path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    workflow = workflow_path.read_text()

    assert "./actions/contract-check" in workflow
    assert "target: composition:usecases" in workflow
    assert "manifest: examples/basic/usecaseapi.yaml" in workflow
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/test_contract_check_action.py::test_ci_workflow_runs_contract_check_action_for_basic_example -q
```

Expected: fail because CI workflow does not yet call the action.

- [ ] **Step 3: Add CI job**

Add a `contract-check` job to `.github/workflows/ci.yml`:

```yaml
  contract-check:
    name: Contract Check
    runs-on: ubuntu-latest
    permissions:
      contents: read
      issues: write
      pull-requests: write
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.13"
      - name: Install uv
        uses: astral-sh/setup-uv@v8.1.0
        with:
          enable-cache: true
          cache-dependency-glob: uv.lock
          cache-suffix: contract-check-python-3.13
      - name: Sync dependencies
        run: uv sync --frozen --extra dev
      - name: Check basic example contract
        uses: ./actions/contract-check
        with:
          target: composition:usecases
          manifest: examples/basic/usecaseapi.yaml
```

If the import target needs `PYTHONPATH`, add it explicitly to the action step:

```yaml
        env:
          PYTHONPATH: examples/basic/src
```

- [ ] **Step 4: Run workflow test**

Run:

```bash
uv run pytest tests/test_contract_check_action.py::test_ci_workflow_runs_contract_check_action_for_basic_example -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml tests/test_contract_check_action.py
git commit -m "ci: run usecaseapi contract check"
```

---

### Task 7: Documentation

**Files:**
- Modify: `docs/manifest.md`
- Modify: `README.md`

- [ ] **Step 1: Add docs**

In `docs/manifest.md`, add a "CI Contract Check" section:

```md
## CI Contract Check

UseCaseAPI treats `usecaseapi.yaml` as the committed contract file. The contract
check action validates that file, checks it against code, and rejects changes to
existing usecase versions.

```yaml
permissions:
  contents: read
  issues: write
  pull-requests: write

steps:
  - uses: actions/checkout@v6
    with:
      fetch-depth: 0
  - uses: actions/setup-python@v6
    with:
      python-version: "3.13"
  - run: uv sync --frozen --extra dev
  - uses: Wisteria30/usecaseapi/actions/contract-check@vX
    with:
      target: composition:usecases
      manifest: usecaseapi.yaml
```

The rule is simple: do not change the same usecase name and version. Add a new
version when the contract changes.
```

Add a README feature bullet linking to this section.

- [ ] **Step 2: Validate docs references**

Run:

```bash
rg -n "contract-check|UseCaseAPI Contract Check|same usecase name and version" README.md docs/manifest.md
```

Expected: matching lines in both docs.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/manifest.md
git commit -m "docs: document contract check action"
```

---

### Task 8: Full Verification

**Files:**
- All changed files

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/test_manifest.py tests/test_contract_check_pr_comment.py tests/test_contract_check_action.py -q
```

Expected: all pass.

- [ ] **Step 2: Run quality checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Expected: all pass.

- [ ] **Step 3: Run full tests and coverage**

Run:

```bash
uv run coverage run -m pytest
uv run coverage report -m
```

Expected: all tests pass and total package coverage remains 100%.

- [ ] **Step 4: Run package build checks**

Run:

```bash
uv build
uv run twine check dist/*
uv run --isolated --no-project --with dist/*.whl scripts/verify_distribution.py
uv run --isolated --no-project --with dist/*.tar.gz scripts/verify_distribution.py
```

Expected: all pass.

- [ ] **Step 5: Final review**

Run:

```bash
git diff --stat origin/main...HEAD
git status --short --branch
```

Expected: diff contains only planned files; working tree is clean after final commit.

---

## Self-Review

Spec coverage:

- Committed `usecaseapi.yaml` validation: Task 3.
- Code synchronization: Task 3 via `manifest ci`.
- PR base/head comparison: Tasks 1, 2, 5, and 6.
- Existing version immutability: Task 1.
- New version additions allowed: Task 1.
- No config file: Task 5 exposes only action inputs.
- PR comment: Task 4 and Task 5.
- Artifact and summary: Task 5.
- Repository CI usage: Task 6.
- Documentation: Task 7.

Placeholder scan:

- No placeholder markers.
- No implicit recovery behavior.
- No hidden dependency installation.

Type consistency:

- `ManifestGuardReport`, `ContractCheckReport`, `guard_manifests`, and
  `render_contract_check_markdown` are introduced before CLI/action tasks use
  them.
