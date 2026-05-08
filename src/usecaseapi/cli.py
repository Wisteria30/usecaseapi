from __future__ import annotations

import argparse
import importlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from .api import UseCaseAPI
from .docs import render_markdown, render_mermaid
from .scaffold import ScaffoldOptions, scaffold_usecase
from .snapshot import diff_snapshots, load_snapshot, snapshot_from_api


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = cast(str, args.command)
    if command == "scaffold":
        return _cmd_scaffold(args)
    if command == "inspect":
        return _cmd_inspect(args)
    if command == "snapshot":
        return _cmd_snapshot(args)
    if command == "docs":
        return _cmd_docs(args)
    if command == "graph":
        return _cmd_graph(args)
    if command == "diff":
        return _cmd_diff(args)
    if command == "check":
        return _cmd_check(args)
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="usecaseapi")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scaffold = subparsers.add_parser("scaffold", help="create a versioned usecase skeleton")
    scaffold.add_argument("name", help="contract name, e.g. orders.place_order")
    version_group = scaffold.add_mutually_exclusive_group()
    version_group.add_argument("--version", type=int, default=None, help="target major version")
    version_group.add_argument(
        "--next",
        action="store_true",
        help="create the next available major version",
    )
    scaffold.add_argument(
        "--from-version",
        type=int,
        default=None,
        help="copy an existing contract version and bump metadata",
    )
    scaffold.add_argument("--contracts-root", default="app/contracts")
    scaffold.add_argument("--implementations-root", default="app/usecases")
    scaffold.add_argument("--tests-root", default="tests")
    scaffold.add_argument("--contracts-package", default="app.contracts")
    scaffold.add_argument("--implementations-package", default="app.usecases")
    scaffold.add_argument("--force", action="store_true")
    scaffold.add_argument("--dry-run", action="store_true")
    scaffold.add_argument("--no-implementation", action="store_true")
    scaffold.add_argument("--no-tests", action="store_true")
    scaffold.add_argument("--no-init", action="store_true")

    for name in ("inspect", "snapshot", "docs", "graph", "check"):
        sub = subparsers.add_parser(name, help=f"{name} a UseCaseAPI instance")
        sub.add_argument("app", help="import path like 'myapp.composition:usecases'")
        if name in {"snapshot", "docs", "graph"}:
            sub.add_argument("--output", "-o", default=None)

    diff = subparsers.add_parser("diff", help="compare two UseCaseAPI snapshots")
    diff.add_argument("old")
    diff.add_argument("new")
    diff.add_argument("--json", action="store_true")

    return parser


def _cmd_scaffold(args: argparse.Namespace) -> int:
    result = scaffold_usecase(
        ScaffoldOptions(
            name=cast(str, args.name),
            version=None if cast(bool, args.next) else cast(int | None, args.version),
            from_version=cast(int | None, args.from_version),
            contracts_root=Path(cast(str, args.contracts_root)),
            implementations_root=Path(cast(str, args.implementations_root)),
            tests_root=Path(cast(str, args.tests_root)),
            contracts_package=cast(str, args.contracts_package),
            implementations_package=cast(str, args.implementations_package),
            force=cast(bool, args.force),
            dry_run=cast(bool, args.dry_run),
            create_implementation=not cast(bool, args.no_implementation),
            create_tests=not cast(bool, args.no_tests),
            create_init=not cast(bool, args.no_init),
        )
    )
    print(f"scaffolded version: v{result.version}")
    for file_path in result.files:
        print(f"created: {file_path}")
    for file_path in result.skipped:
        print(f"skipped: {file_path}")
    return 0


def _cmd_inspect(args: argparse.Namespace) -> int:
    api = _load_api(cast(str, args.app))
    print(json.dumps(snapshot_from_api(api), ensure_ascii=False, indent=2))
    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    api = _load_api(cast(str, args.app))
    payload = json.dumps(snapshot_from_api(api), ensure_ascii=False, indent=2) + "\n"
    _write_or_print(payload, cast(str | None, args.output))
    return 0


def _cmd_docs(args: argparse.Namespace) -> int:
    api = _load_api(cast(str, args.app))
    _write_or_print(render_markdown(api), cast(str | None, args.output))
    return 0


def _cmd_graph(args: argparse.Namespace) -> int:
    api = _load_api(cast(str, args.app))
    _write_or_print(render_mermaid(api), cast(str | None, args.output))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    api = _load_api(cast(str, args.app))
    api.validate(require_handlers=True)
    print("UseCaseAPI check passed")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    diff = diff_snapshots(load_snapshot(cast(str, args.old)), load_snapshot(cast(str, args.new)))
    if cast(bool, args.json):
        print(json.dumps(diff.to_dict(), ensure_ascii=False, indent=2))
    else:
        for label, items in (
            ("Breaking", diff.breaking),
            ("Warnings", diff.warnings),
            ("Additions", diff.additions),
        ):
            print(label + ":")
            if items:
                for item in items:
                    print(f"  - {item}")
            else:
                print("  - none")
    return 1 if diff.has_breaking_changes else 0


def _load_api(import_path: str) -> UseCaseAPI[Any]:
    module_name, separator, attribute_name = import_path.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError("app import path must look like 'module:attribute'")
    module = importlib.import_module(module_name)
    value = getattr(module, attribute_name)
    if not isinstance(value, UseCaseAPI):
        raise TypeError(f"{import_path!r} is not a UseCaseAPI instance")
    return value


def _write_or_print(content: str, output: str | None) -> None:
    if output is None:
        print(content, end="")
        return
    Path(output).write_text(content)


if __name__ == "__main__":
    raise SystemExit(main())
