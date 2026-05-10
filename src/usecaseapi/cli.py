"""Command-line interface for inspecting and scaffolding UseCaseAPI projects."""

from __future__ import annotations

import importlib
import json
import sys

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import click
import typer

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

app = typer.Typer(help="Inspect and scaffold UseCaseAPI projects.", no_args_is_help=True)
manifest_app = typer.Typer(help="Export, validate, scaffold, or check Manifest files.")
app.add_typer(manifest_app, name="manifest")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit code."""
    args = list(argv) if argv is not None else None
    if args == []:
        args = ["--help"]
    try:
        result = app(args=args, prog_name="usecaseapi", standalone_mode=False)
    except click.exceptions.Exit as exc:
        return exc.exit_code
    except click.ClickException as exc:
        exc.show()
        return exc.exit_code
    if isinstance(result, int):
        return result
    return 0


@app.command()
def scaffold(
    package: Annotated[str, typer.Argument(help="Python package name, e.g. commerce")],
    usecase: Annotated[str, typer.Argument(help="Usecase name, e.g. place_order")],
    version: Annotated[int | None, typer.Option(help="Target major version")] = None,
    next_: Annotated[
        bool,
        typer.Option(
            "--next",
            help="Create the next available major version",
        ),
    ] = False,
    force: Annotated[bool, typer.Option(help="Overwrite generated files")] = False,
    dry_run: Annotated[bool, typer.Option(help="Print files without writing them")] = False,
    output_root: Annotated[
        Path,
        typer.Option(help="Directory where namespace directories are generated"),
    ] = Path("."),
    tests_root: Annotated[Path, typer.Option(help="Directory where tests are generated")] = Path(
        "tests"
    ),
) -> None:
    """Create a versioned usecase skeleton."""
    if version is not None and next_:
        raise typer.BadParameter("--version and --next cannot be used together")
    name = f"{package}.{usecase}"
    result = scaffold_usecase(
        ScaffoldOptions(
            name=name,
            version=version,
            next=next_,
            output_root=output_root,
            tests_root=tests_root,
            force=force,
            dry_run=dry_run,
        )
    )
    typer.echo(f"scaffolded version: v{result.version}")
    for file_path in result.files:
        typer.echo(f"created: {file_path}")


@app.command()
def inspect(
    target: Annotated[str, typer.Argument(help="Import path like 'composition:usecases'")],
) -> None:
    """Print a UseCaseAPI Manifest as YAML."""
    api = _load_api(target)
    typer.echo(manifest_to_yaml(manifest_from_api(api)), nl=False)


@app.command()
def docs(
    manifest: Annotated[Path, typer.Argument(help="Path to a .ucase.yaml Manifest")],
    output: Annotated[str | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Write or print Markdown docs from a UseCaseAPI Manifest."""
    _write_or_print(render_manifest_markdown(load_manifest(manifest)), output)


@app.command()
def graph(
    manifest: Annotated[Path, typer.Argument(help="Path to a .ucase.yaml Manifest")],
    output: Annotated[str | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Write or print a Mermaid graph from a UseCaseAPI Manifest."""
    _write_or_print(render_manifest_graph(load_manifest(manifest)), output)


@app.command()
def check(
    target: Annotated[str, typer.Argument(help="Import path like 'composition:usecases'")],
) -> None:
    """Validate a UseCaseAPI instance."""
    api = _load_api(target)
    api.validate(require_handlers=True)
    typer.echo("UseCaseAPI check passed")


@app.command()
def diff(
    old: Annotated[Path, typer.Argument(help="Old Manifest path")],
    new: Annotated[Path, typer.Argument(help="New Manifest path")],
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON output")] = False,
) -> None:
    """Compare two UseCaseAPI Manifests."""
    manifest_diff = diff_manifests(load_manifest(old), load_manifest(new))
    if json_output:
        typer.echo(json.dumps(manifest_diff.to_dict(), ensure_ascii=False, indent=2))
    else:
        _echo_diff(manifest_diff.breaking, manifest_diff.warnings, manifest_diff.additions)
    if manifest_diff.has_breaking_changes:
        raise typer.Exit(1)


@manifest_app.command("export")
def manifest_export(
    target: Annotated[str, typer.Argument(help="Import path like 'composition:usecases'")],
    output: Annotated[str | None, typer.Option("--output", "-o")] = None,
    project: Annotated[str | None, typer.Option(help="Project name for Manifest metadata")] = None,
    package: Annotated[
        str | None, typer.Option(help="Python package name for layout metadata")
    ] = None,
    contracts_root: Annotated[
        str,
        typer.Option(help="Root used to trim contract source paths"),
    ] = "app/contracts",
    implementations_root: Annotated[
        str,
        typer.Option(help="Default implementation root for generated Manifest entries"),
    ] = "app/usecases",
    include_json_schema: Annotated[
        bool,
        typer.Option(help="Include Pydantic JSON schemas in the Manifest"),
    ] = False,
) -> None:
    """Export a UseCaseAPI Manifest from a composed API object."""
    api = _load_api(target)
    manifest = manifest_from_api(
        api,
        project=project,
        package=package,
        contracts_root=contracts_root,
        implementations_root=implementations_root,
        include_json_schema=include_json_schema,
    )
    if output is None:
        typer.echo(manifest_to_yaml(manifest), nl=False)
        return
    dump_manifest(manifest, output)


@manifest_app.command("validate")
def manifest_validate(
    path: Annotated[Path, typer.Argument(help="Path to a .ucase.yaml Manifest")],
) -> None:
    """Validate a UseCaseAPI Manifest."""
    validate_manifest(load_manifest(path))
    typer.echo("UseCaseAPI manifest validation passed")


@manifest_app.command("scaffold")
def manifest_scaffold(
    path: Annotated[Path, typer.Argument(help="Path to a .ucase.yaml Manifest")],
    root: Annotated[Path, typer.Option(help="Root directory for generated files")] = Path("."),
    force: Annotated[bool, typer.Option(help="Overwrite generated files")] = False,
    dry_run: Annotated[bool, typer.Option(help="Print files without writing them")] = False,
    no_implementation: Annotated[
        bool,
        typer.Option(help="Do not generate implementation skeletons"),
    ] = False,
) -> None:
    """Generate Python contract and implementation skeletons from a Manifest."""
    result = scaffold_from_manifest(
        load_manifest(path),
        root=root,
        force=force,
        dry_run=dry_run,
        create_implementation=not no_implementation,
    )
    for file_path in result.files:
        typer.echo(f"created: {file_path}")
    for file_path in result.skipped:
        typer.echo(f"skipped: {file_path}")


@manifest_app.command("check-sync")
def manifest_check_sync(
    target: Annotated[str, typer.Argument(help="Import path like 'composition:usecases'")],
    path: Annotated[Path, typer.Argument(help="Path to a .ucase.yaml Manifest")],
) -> None:
    """Check that code and a Manifest describe the same contract catalog."""
    api = _load_api(target)
    manifest_diff = diff_manifest_with_api(api, load_manifest(path))
    if manifest_diff.has_breaking_changes or manifest_diff.warnings or manifest_diff.additions:
        _echo_diff(manifest_diff.breaking, manifest_diff.warnings, manifest_diff.additions)
        raise typer.Exit(1)
    typer.echo("UseCaseAPI manifest is synchronized")


def _echo_diff(
    breaking: Sequence[str],
    warnings: Sequence[str],
    additions: Sequence[str],
) -> None:
    for label, items in (
        ("Breaking", breaking),
        ("Warnings", warnings),
        ("Additions", additions),
    ):
        typer.echo(label + ":")
        if items:
            for item in items:
                typer.echo(f"  - {item}")
        else:
            typer.echo("  - none")


def _load_api(import_path: str) -> UseCaseAPI[Any]:
    module_name, separator, attribute_name = import_path.partition(":")
    if not separator or not module_name or not attribute_name:
        raise ValueError("import path must look like 'module:attribute'")
    module = importlib.import_module(module_name)
    value = getattr(module, attribute_name)
    if not isinstance(value, UseCaseAPI):
        raise TypeError(f"{import_path!r} is not a UseCaseAPI instance")
    return value


def _write_or_print(content: str, output: str | None) -> None:
    if output is None:
        typer.echo(content, nl=False)
        return
    Path(output).write_text(content)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
