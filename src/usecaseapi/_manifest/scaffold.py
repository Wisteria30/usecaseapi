"""Manifest implementation package."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .common import *
from .openapi import *
from .validation import *


def scaffold_from_manifest(
    manifest: Mapping[str, Any],
    *,
    root: str | Path = ".",
    force: bool = False,
    dry_run: bool = False,
    create_implementation: bool = True,
) -> ManifestScaffoldResult:
    """Generate Python contract, implementation, and test skeletons from a Manifest."""
    validate_manifest(manifest)
    semantic = (
        semantic_from_openapi_manifest(manifest)
        if manifest.get("openapi") == OPENAPI_VERSION
        else manifest
    )
    root_path = Path(root).resolve()
    layout = semantic.get("layout")
    layout_mapping = layout if isinstance(layout, Mapping) else {}
    contracts_root = string_or_default(layout_mapping.get("contracts_root"), "app/contracts")
    implementations_root = string_or_default(
        layout_mapping.get("implementations_root"),
        "app/usecases",
    )
    tests_root = string_or_default(layout_mapping.get("tests_root"), "tests")
    package = layout_mapping.get("package")
    package_name = package if isinstance(package, str) and package else None

    created: list[Path] = []
    skipped: list[Path] = []
    for usecase in usecase_items_from_semantic(semantic):
        source = required_mapping(usecase.get("source"), "usecase.source")
        contract_path = string_or_default(
            source.get("contract_file"),
            default_contract_file(usecase, contracts_root=contracts_root),
        )
        validate_contract_file_module(
            contract_path,
            required_string(source, "contract_module"),
            package=package_name,
        )
        contract_file = safe_manifest_file_under_root(
            root_path,
            contract_path,
            context="source.contract_file",
        )
        implementation_path = string_or_default(
            source.get("implementation_file"),
            default_implementation_file(usecase, implementations_root=implementations_root),
        )
        implementation_file = safe_manifest_file_under_root(
            root_path,
            implementation_path,
            context="source.implementation_file",
        )
        test_path = default_manifest_test_file(usecase, tests_root=tests_root)
        test_file = safe_manifest_file_under_root(
            root_path,
            test_path,
            context="layout.tests_root",
        )

        write_generated_file(
            contract_file,
            render_contract_module(usecase),
            force=force,
            dry_run=dry_run,
        )
        created.append(contract_file)

        if create_implementation:
            if implementation_file.exists() and not force:
                skipped.append(implementation_file)
            else:
                write_generated_file(
                    implementation_file,
                    render_implementation_module(usecase),
                    force=force,
                    dry_run=dry_run,
                )
                created.append(implementation_file)

            if test_file.exists() and not force:
                skipped.append(test_file)
            else:
                write_generated_file(
                    test_file,
                    render_manifest_test_module(
                        usecase,
                        implementation_module=module_from_python_file(
                            Path(implementation_path),
                            package=package_name,
                        ),
                    ),
                    force=force,
                    dry_run=dry_run,
                )
                created.append(test_file)

        if not dry_run:
            ensure_init_files(contract_file.parent, stop_at=root_path)
            if create_implementation:
                ensure_init_files(implementation_file.parent, stop_at=root_path)

    return ManifestScaffoldResult(files=tuple(created), skipped=tuple(skipped))


def safe_manifest_file_under_root(root_path: Path, manifest_path: str, *, context: str) -> Path:
    """Resolve a Manifest file path and reject writes outside the scaffold root."""
    validate_manifest_file_path(manifest_path, context=context)
    resolved_root = root_path.resolve()
    resolved_path = (resolved_root / manifest_path).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        raise ManifestError(f"{context} must stay under the scaffold root")
    return resolved_path


def render_contract_module(usecase: Mapping[str, Any]) -> str:
    """Render one contract module from one Manifest usecase."""
    validate_usecase_manifest(usecase, seen_keys=set(), index=0)
    source = required_mapping(usecase.get("source"), "usecase.source")
    protocol_class = required_string(source, "protocol_class")
    ref = required_string(source, "ref")
    input_name = required_string(usecase, "input")
    output_name = required_string(usecase, "output")
    name = required_string(usecase, "name")
    version = required_int(usecase, "version")
    description = usecase.get("description")
    stable = bool(usecase.get("stable", True))
    deprecated = bool(usecase.get("deprecated", False))
    superseded_by = usecase.get("superseded_by")
    tags = string_list(usecase.get("tags"))
    raises = string_list(usecase.get("raises"))
    known_errors = string_list(usecase.get("known_errors"))
    models = manifest_models(usecase)
    errors = manifest_errors(usecase)

    type_exprs = collect_type_exprs(models, errors)
    lines: list[str] = []
    if isinstance(description, str):
        lines.extend([py_string_literal(description), ""])
    lines.extend(["from __future__ import annotations", ""])
    lines.extend(stdlib_import_lines(type_exprs))
    lines.append(f"from typing import {', '.join(typing_imports(type_exprs, errors))}")
    lines.extend(["", "from usecaseapi import ("])
    for import_name in usecaseapi_imports(errors):
        lines.append(f"    {import_name},")
    lines.extend([")", "", ""])

    for model in models:
        lines.extend(render_model_class(model))
        lines.extend(["", ""])

    for error in errors:
        lines.extend(render_error_class(error))
        lines.extend(["", ""])

    lines.extend(
        render_contract_binding(
            protocol_class=protocol_class,
            input_name=input_name,
            output_name=output_name,
            ref=ref,
            name=name,
            version=version,
            raises=raises,
            known_errors=known_errors,
            stable=stable,
            deprecated=deprecated,
            superseded_by=superseded_by,
            description=description,
            tags=tags,
        )
    )
    return "\n".join(lines)


def render_implementation_module(usecase: Mapping[str, Any]) -> str:
    """Render one implementation skeleton from one Manifest usecase."""
    validate_usecase_manifest(usecase, seen_keys=set(), index=0)
    source = required_mapping(usecase.get("source"), "usecase.source")
    contract_module = required_string(source, "contract_module")
    protocol_class = required_string(source, "protocol_class")
    implementation_class = string_or_default(
        source.get("implementation_class"),
        protocol_class + "Impl",
    )
    input_name = required_string(usecase, "input")
    output_name = required_string(usecase, "output")
    description = usecase.get("description")
    class_description = (
        description
        if isinstance(description, str)
        else f"Implementation skeleton for {protocol_class}."
    )
    lines: list[str] = []
    if isinstance(description, str):
        lines.extend([py_string_literal(description), ""])
    lines.extend(
        [
            "from __future__ import annotations",
            "",
            f"from {contract_module} import (",
            f"    {input_name},",
            f"    {output_name},",
            ")",
            "",
            "",
            f"class {implementation_class}:",
            f"    {py_string_literal(class_description)}",
            "",
            f"    async def __call__(self, input: {input_name}, /) -> {output_name}:",
            f"        {py_string_literal(f'Implement {implementation_class}.__call__ before using this class.')}",
            f'        raise NotImplementedError("{implementation_class}.__call__ is not implemented")',
            "",
        ]
    )
    return "\n".join(lines)


def render_manifest_test_module(usecase: Mapping[str, Any], *, implementation_module: str) -> str:
    """Render one pytest module for a Manifest scaffolded usecase."""
    validate_usecase_manifest(usecase, seen_keys=set(), index=0)
    source = required_mapping(usecase.get("source"), "usecase.source")
    contract_module = required_string(source, "contract_module")
    protocol_class = required_string(source, "protocol_class")
    ref = required_string(source, "ref")
    implementation_class = string_or_default(
        source.get("implementation_class"),
        protocol_class + "Impl",
    )
    name = required_string(usecase, "name")
    version = required_int(usecase, "version")
    test_name = name.split(".")[-1]
    return f'''{py_string_literal(f"Tests for {name} v{version}.")}

from __future__ import annotations

from {contract_module} import (
    {ref},
    {protocol_class},
)
from {implementation_module} import (
    {implementation_class},
)


def test_{test_name}_contract_metadata() -> None:
    """Contract metadata matches the Manifest usecase identity."""
    assert {ref}.contract.name == "{name}"
    assert {ref}.contract.version == {version}


def test_{test_name}_usecase_matches_contract() -> None:
    """Usecase implementation structurally matches the contract Protocol."""
    usecase: {protocol_class} = {implementation_class}()
    assert usecase is not None
'''


def render_manifest_markdown(manifest: Mapping[str, Any]) -> str:
    """Render human-readable Markdown docs from a Manifest."""
    validate_manifest(manifest)
    lines = ["# UseCaseAPI Manifest", ""]
    metadata = manifest.get("metadata")
    if isinstance(metadata, Mapping) and isinstance(metadata.get("name"), str):
        lines.extend([f"Project: `{metadata['name']}`", ""])
    for item in usecase_items(manifest):
        key = usecase_key(item)
        lines.extend([f"## {required_string(item, 'name')} v{required_int(item, 'version')}", ""])
        description = item.get("description")
        if isinstance(description, str) and description:
            lines.extend([description, ""])
        lines.extend(
            [
                f"- Key: `{key}`",
                f"- Input: `{required_string(item, 'input')}`",
                f"- Output: `{required_string(item, 'output')}`",
            ]
        )
        uses = string_list(item.get("uses"))
        if uses:
            lines.append("- Uses: " + ", ".join(f"`{use}`" for use in uses))
        raises = string_list(item.get("raises"))
        if raises:
            lines.append("- Raises: " + ", ".join(f"`{error}`" for error in raises))
        known_errors = string_list(item.get("known_errors"))
        if known_errors:
            lines.append("- Known errors: " + ", ".join(f"`{error}`" for error in known_errors))
        lines.extend(render_markdown_source(item))
        lines.extend(render_markdown_models(item))
        lines.extend(render_markdown_errors(item))
        lines.append("")
    return "\n".join(lines)


def render_markdown_source(item: Mapping[str, Any]) -> list[str]:
    """Render source mapping for one usecase."""
    source = required_mapping(item.get("source"), "source")
    lines = ["", "### Source", ""]
    for key in (
        "contract_module",
        "protocol_class",
        "ref",
        "contract_file",
        "implementation_class",
        "implementation_file",
        "binding_factory",
        "binding_file",
    ):
        value = source.get(key)
        if isinstance(value, str) and value:
            lines.append(f"- `{key}`: `{value}`")
    return lines


def render_markdown_models(item: Mapping[str, Any]) -> list[str]:
    """Render model descriptions and fields for one usecase."""
    models = manifest_models(item)
    lines = ["", "### Models", ""]
    for model in models:
        lines.append(f"#### `{required_string(model, 'name')}`")
        description = model.get("description")
        if isinstance(description, str) and description:
            lines.extend(["", description])
        fields = manifest_fields(model)
        if fields:
            lines.extend(
                [
                    "",
                    "| Field | Type | Required | Description |",
                    "| --- | --- | --- | --- |",
                ]
            )
            for field in fields:
                field_description = field.get("description")
                description_text = field_description if isinstance(field_description, str) else "-"
                lines.append(
                    "| "
                    f"`{required_string(field, 'name')}` | "
                    f"`{required_string(field, 'type')}` | "
                    f"{'yes' if field.get('required') is True else 'no'} | "
                    f"{description_text} |"
                )
        else:
            lines.extend(["", "_No fields._"])
        lines.append("")
    if lines[-1] == "":
        lines.pop()
    return lines


def render_markdown_errors(item: Mapping[str, Any]) -> list[str]:
    """Render public error contract information for one usecase."""
    errors = manifest_errors(item)
    if not errors:
        return []
    lines = [
        "",
        "### Errors",
        "",
        "| Error | Base | Code | Description | Fields |",
        "| --- | --- | --- | --- | --- |",
    ]
    for error in errors:
        description = error.get("description")
        description_text = description if isinstance(description, str) else "-"
        fields = ", ".join(
            f"`{required_string(field, 'name')}: {required_string(field, 'type')}`"
            for field in manifest_fields(error)
        )
        lines.append(
            "| "
            f"`{required_string(error, 'name')}` | "
            f"`{required_string(error, 'base')}` | "
            f"`{required_string(error, 'code')}` | "
            f"{description_text} | "
            f"{fields or '-'} |"
        )
    return lines


def render_manifest_graph(manifest: Mapping[str, Any]) -> str:
    """Render a Mermaid graph from a Manifest."""
    validate_manifest(manifest)
    lines = ["graph TD"]
    for item in usecase_items(manifest):
        key = usecase_key(item)
        current_node_id = node_id(key)
        lines.append(f'  {current_node_id}["{key}"]')
        for used_key in string_list(item.get("uses")):
            lines.append(f"  {current_node_id} --> {node_id(used_key)}")
    return "\n".join(lines) + "\n"
