"""Command-line interface for inspecting and scaffolding UseCaseAPI projects."""

from __future__ import annotations

import argparse
import importlib
import json

from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from .api import UseCaseAPI
from .manifest import (
    diff_manifest_with_api,
    diff_manifests,
    dump_manifest,
    load_manifest,
    manifest_from_api,
    manifest_to_yaml,
    render_manifest_graph,
    render_manifest_markdown,
    scaffold_from_manifest,
    validate_manifest,
)
from .scaffold import ScaffoldOptions, scaffold_usecase


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = cast(str, args.command)
    if command == "scaffold":
        return _cmd_scaffold(args)
    if command == "inspect":
        return _cmd_inspect(args)
    if command == "docs":
        return _cmd_docs(args)
    if command == "graph":
        return _cmd_graph(args)
    if command == "diff":
        return _cmd_diff(args)
    if command == "check":
        return _cmd_check(args)
    if command == "manifest":
        return _cmd_manifest(args)
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

    inspect = subparsers.add_parser("inspect", help="inspect a UseCaseAPI instance")
    inspect.add_argument("app", help="import path like 'myapp.composition:usecases'")

    check = subparsers.add_parser("check", help="check a UseCaseAPI instance")
    check.add_argument("app", help="import path like 'myapp.composition:usecases'")

    for name in ("docs", "graph"):
        sub = subparsers.add_parser(name, help=f"{name} a UseCaseAPI Manifest")
        sub.add_argument("manifest", help="path to a .ucase.yaml Manifest")
        sub.add_argument("--output", "-o", default=None)

    diff = subparsers.add_parser("diff", help="compare two UseCaseAPI manifests")
    diff.add_argument("old")
    diff.add_argument("new")
    diff.add_argument("--json", action="store_true")

    manifest = subparsers.add_parser(
        "manifest",
        help="export, validate, scaffold, or check .ucase.yaml files",
    )
    manifest_subparsers = manifest.add_subparsers(dest="manifest_command", required=True)

    manifest_export = manifest_subparsers.add_parser("export", help="export a UseCaseAPI Manifest")
    manifest_export.add_argument("app", help="import path like 'myapp.composition:usecases'")
    manifest_export.add_argument("--output", "-o", default=None)
    manifest_export.add_argument("--project", default=None)
    manifest_export.add_argument("--package", default=None)
    manifest_export.add_argument("--contracts-root", default="app/contracts")
    manifest_export.add_argument("--implementations-root", default="app/usecases")
    manifest_export.add_argument("--include-json-schema", action="store_true")

    manifest_validate = manifest_subparsers.add_parser(
        "validate",
        help="validate a UseCaseAPI Manifest",
    )
    manifest_validate.add_argument("path")

    manifest_scaffold = manifest_subparsers.add_parser(
        "scaffold",
        help="generate Python contract and implementation skeletons from a Manifest",
    )
    manifest_scaffold.add_argument("path")
    manifest_scaffold.add_argument("--root", default=".")
    manifest_scaffold.add_argument("--force", action="store_true")
    manifest_scaffold.add_argument("--dry-run", action="store_true")
    manifest_scaffold.add_argument("--no-implementation", action="store_true")

    manifest_check_sync = manifest_subparsers.add_parser(
        "check-sync",
        help="check that code and a Manifest describe the same contract catalog",
    )
    manifest_check_sync.add_argument("app", help="import path like 'myapp.composition:usecases'")
    manifest_check_sync.add_argument("path")

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
    print(manifest_to_yaml(manifest_from_api(api)), end="")
    return 0


def _cmd_docs(args: argparse.Namespace) -> int:
    manifest = load_manifest(cast(str, args.manifest))
    _write_or_print(render_manifest_markdown(manifest), cast(str | None, args.output))
    return 0


def _cmd_graph(args: argparse.Namespace) -> int:
    manifest = load_manifest(cast(str, args.manifest))
    _write_or_print(render_manifest_graph(manifest), cast(str | None, args.output))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    api = _load_api(cast(str, args.app))
    api.validate(require_handlers=True)
    print("UseCaseAPI check passed")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    diff = diff_manifests(load_manifest(cast(str, args.old)), load_manifest(cast(str, args.new)))
    if cast(bool, args.json):
        print(json.dumps(diff.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_diff(diff.breaking, diff.warnings, diff.additions)
    return 1 if diff.has_breaking_changes else 0


def _cmd_manifest(args: argparse.Namespace) -> int:
    command = cast(str, args.manifest_command)
    if command == "export":
        return _cmd_manifest_export(args)
    if command == "validate":
        return _cmd_manifest_validate(args)
    if command == "scaffold":
        return _cmd_manifest_scaffold(args)
    if command == "check-sync":
        return _cmd_manifest_check_sync(args)
    raise ValueError(f"unknown manifest command: {command}")


def _cmd_manifest_export(args: argparse.Namespace) -> int:
    api = _load_api(cast(str, args.app))
    manifest = manifest_from_api(
        api,
        project=cast(str | None, args.project),
        package=cast(str | None, args.package),
        contracts_root=cast(str, args.contracts_root),
        implementations_root=cast(str, args.implementations_root),
        include_json_schema=cast(bool, args.include_json_schema),
    )
    output = cast(str | None, args.output)
    if output is None:
        print(manifest_to_yaml(manifest), end="")
    else:
        dump_manifest(manifest, output)
    return 0


def _cmd_manifest_validate(args: argparse.Namespace) -> int:
    validate_manifest(load_manifest(cast(str, args.path)))
    print("UseCaseAPI manifest validation passed")
    return 0


def _cmd_manifest_scaffold(args: argparse.Namespace) -> int:
    result = scaffold_from_manifest(
        load_manifest(cast(str, args.path)),
        root=cast(str, args.root),
        force=cast(bool, args.force),
        dry_run=cast(bool, args.dry_run),
        create_implementation=not cast(bool, args.no_implementation),
    )
    for file_path in result.files:
        print(f"created: {file_path}")
    for file_path in result.skipped:
        print(f"skipped: {file_path}")
    return 0


def _cmd_manifest_check_sync(args: argparse.Namespace) -> int:
    api = _load_api(cast(str, args.app))
    diff = diff_manifest_with_api(api, load_manifest(cast(str, args.path)))
    if diff.has_breaking_changes or diff.warnings or diff.additions:
        _print_diff(diff.breaking, diff.warnings, diff.additions)
        return 1
    print("UseCaseAPI manifest is synchronized")
    return 0


def _print_diff(
    breaking: Sequence[str],
    warnings: Sequence[str],
    additions: Sequence[str],
) -> None:
    for label, items in (
        ("Breaking", breaking),
        ("Warnings", warnings),
        ("Additions", additions),
    ):
        print(label + ":")
        if items:
            for item in items:
                print(f"  - {item}")
        else:
            print("  - none")


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
