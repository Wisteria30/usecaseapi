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
from .docs import render_markdown, render_mermaid
from .scaffold import ScaffoldOptions, scaffold_usecase
from .snapshot import diff_snapshots, load_snapshot, snapshot_from_api

app = typer.Typer(help="Inspect and scaffold UseCaseAPI projects.", no_args_is_help=True)


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
    """Print a UseCaseAPI snapshot as JSON."""
    api = _load_api(target)
    typer.echo(json.dumps(snapshot_from_api(api), ensure_ascii=False, indent=2))


@app.command()
def snapshot(
    target: Annotated[str, typer.Argument(help="Import path like 'composition:usecases'")],
    output: Annotated[str | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Write or print a UseCaseAPI snapshot."""
    api = _load_api(target)
    payload = json.dumps(snapshot_from_api(api), ensure_ascii=False, indent=2) + "\n"
    _write_or_print(payload, output)


@app.command()
def docs(
    target: Annotated[str, typer.Argument(help="Import path like 'composition:usecases'")],
    output: Annotated[str | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Write or print Markdown docs for a UseCaseAPI instance."""
    api = _load_api(target)
    _write_or_print(render_markdown(api), output)


@app.command()
def graph(
    target: Annotated[str, typer.Argument(help="Import path like 'composition:usecases'")],
    output: Annotated[str | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Write or print a Mermaid graph for a UseCaseAPI instance."""
    api = _load_api(target)
    _write_or_print(render_mermaid(api), output)


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
    old: Annotated[str, typer.Argument(help="Old snapshot path")],
    new: Annotated[str, typer.Argument(help="New snapshot path")],
    json_output: Annotated[bool, typer.Option("--json", help="Print JSON output")] = False,
) -> None:
    """Compare two UseCaseAPI snapshots."""
    contract_diff = diff_snapshots(load_snapshot(old), load_snapshot(new))
    if json_output:
        typer.echo(json.dumps(contract_diff.to_dict(), ensure_ascii=False, indent=2))
    else:
        for label, items in (
            ("Breaking", contract_diff.breaking),
            ("Warnings", contract_diff.warnings),
            ("Additions", contract_diff.additions),
        ):
            typer.echo(label + ":")
            if items:
                for item in items:
                    typer.echo(f"  - {item}")
            else:
                typer.echo("  - none")
    if contract_diff.has_breaking_changes:
        raise typer.Exit(1)


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
