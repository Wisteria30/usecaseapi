"""YAML Manifest catalog support for UseCaseAPI."""

from __future__ import annotations

import ast
import inspect
import sys
import types

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, Union, cast, get_args, get_origin, get_type_hints

import yaml

from pydantic.fields import FieldInfo

from .api import UseCaseAPI
from .contracts import UseCaseRef
from .errors import UseCaseError
from .model import Model

MANIFEST_KIND = "usecaseapi.manifest/v1"
MANIFEST_MEDIA_TYPE = "application/vnd.usecaseapi.manifest.v1+yaml"
MANIFEST_EXTENSION = ".ucase.yaml"
PROTOCOL_KIND = "usecaseapi.inprocess.async_call/v1"

_BUILTIN_TYPE_NAMES = {
    "Any",
    "None",
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "list",
    "dict",
    "set",
    "tuple",
    "Literal",
    "UUID",
    "date",
    "datetime",
    "Decimal",
}


class ManifestError(ValueError):
    """Raised when a Manifest cannot be parsed, validated, or generated."""


@dataclass(frozen=True, slots=True)
class ManifestScaffoldResult:
    """Files planned or created from a Manifest."""

    files: tuple[Path, ...]
    skipped: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ManifestDiff:
    """Semantic differences between two Manifest catalogs."""

    breaking: tuple[str, ...]
    warnings: tuple[str, ...]
    additions: tuple[str, ...]

    @property
    def has_breaking_changes(self) -> bool:
        """Whether the diff contains at least one breaking change."""
        return bool(self.breaking)

    def to_dict(self) -> dict[str, list[str]]:
        """Return a JSON-friendly representation."""
        return {
            "breaking": list(self.breaking),
            "warnings": list(self.warnings),
            "additions": list(self.additions),
        }


def manifest_from_api(
    api: UseCaseAPI[Any],
    *,
    project: str | None = None,
    package: str | None = None,
    contracts_root: str | None = None,
    implementations_root: str | None = None,
    include_json_schema: bool = False,
) -> dict[str, Any]:
    """Create a Manifest dictionary from a registered UseCaseAPI instance."""
    resolved_package = package or infer_package(api)
    resolved_implementations_root = implementations_root or infer_implementations_root(
        api,
        package=resolved_package,
    )
    resolved_contracts_root = contracts_root or infer_contracts_root(
        package=resolved_package,
        implementations_root=resolved_implementations_root,
    )
    uses_by_key = {binding.ref.key: tuple(sorted(binding.uses)) for binding in api.bindings}
    binding_by_key = {binding.ref.key: binding for binding in api.bindings}
    usecases: list[dict[str, Any]] = []
    for ref in sorted(api.contracts, key=lambda item: item.key):
        binding = binding_by_key.get(ref.key)
        item = ref_to_manifest_usecase(
            ref,
            uses=uses_by_key.get(ref.key, ()),
            include_json_schema=include_json_schema,
            contracts_root=resolved_contracts_root,
            implementations_root=resolved_implementations_root,
            package=resolved_package,
        )
        if binding is not None:
            source = cast(dict[str, Any], required_mapping(item.setdefault("source", {}), "source"))
            source["binding_factory"] = qualname(binding.factory)
            binding_file = source_file(binding.factory)
            if binding_file is not None:
                source["binding_file"] = binding_file
            if binding.description is not None:
                item["binding_description"] = binding.description
            if binding.tags:
                item["binding_tags"] = list(binding.tags)
        usecases.append(item)

    layout: dict[str, Any] = {
        "contracts_root": resolved_contracts_root,
        "implementations_root": resolved_implementations_root,
    }
    if resolved_package is not None:
        layout["package"] = resolved_package

    manifest: dict[str, Any] = {
        "kind": MANIFEST_KIND,
        "metadata": {"name": project or "usecaseapi-project"},
        "runtime": {
            "language": "python",
            "python": ">=3.12,<3.15",
            "protocol": PROTOCOL_KIND,
        },
        "layout": layout,
        "usecases": usecases,
    }
    validate_manifest(manifest)
    return manifest


def infer_package(api: UseCaseAPI[Any]) -> str | None:
    """Infer a single package from registered usecase names."""
    packages = {ref.contract.name.split(".")[0] for ref in api.contracts}
    if len(packages) == 1:
        return next(iter(packages))
    return None


def infer_implementations_root(api: UseCaseAPI[Any], *, package: str | None) -> str:
    """Infer the v1.1 implementation root from contract source files."""
    if package is None:
        return "src"
    for ref in api.contracts:
        file_name = source_file(ref.protocol)
        if file_name is None:
            continue
        parts = Path(file_name).parts
        for index, part in enumerate(parts):
            if part != package:
                continue
            if index > 0 and parts[index - 1] == "src":
                return "src"
            if index == 0:
                return "."
    return "src"


def infer_contracts_root(*, package: str | None, implementations_root: str) -> str:
    """Infer the contract root used for source path trimming."""
    if package is None:
        return implementations_root
    if implementations_root == ".":
        return package
    return str(Path(implementations_root) / package)


def dump_manifest(manifest: Mapping[str, Any], path: str | Path) -> None:
    """Write a validated Manifest YAML file."""
    validate_manifest(manifest)
    Path(path).write_text(manifest_to_yaml(manifest))


def manifest_to_yaml(manifest: Mapping[str, Any]) -> str:
    """Serialize a Manifest mapping to stable YAML text."""
    validate_manifest(manifest)
    return yaml.safe_dump(
        dict(manifest),
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load and validate a Manifest YAML file."""
    payload = yaml.safe_load(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ManifestError("manifest must be a YAML mapping")
    manifest = dict(payload)
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate Manifest shape and UseCaseAPI-specific cross references."""
    if manifest.get("kind") != MANIFEST_KIND:
        raise ManifestError(f"manifest kind must be {MANIFEST_KIND!r}")
    usecases = manifest.get("usecases")
    if not isinstance(usecases, list) or not usecases:
        raise ManifestError("manifest.usecases must be a non-empty list")

    seen_keys: set[str] = set()
    for index, item in enumerate(usecases):
        if not isinstance(item, Mapping):
            raise ManifestError(f"usecases[{index}] must be a mapping")
        validate_usecase_manifest(item, seen_keys=seen_keys, index=index)


def scaffold_from_manifest(
    manifest: Mapping[str, Any],
    *,
    root: str | Path = ".",
    force: bool = False,
    dry_run: bool = False,
    create_implementation: bool = True,
) -> ManifestScaffoldResult:
    """Generate Python contract and implementation skeletons from a Manifest."""
    validate_manifest(manifest)
    root_path = Path(root)
    layout = manifest.get("layout")
    layout_mapping = layout if isinstance(layout, Mapping) else {}
    contracts_root = string_or_default(layout_mapping.get("contracts_root"), "app/contracts")
    implementations_root = string_or_default(
        layout_mapping.get("implementations_root"),
        "app/usecases",
    )

    created: list[Path] = []
    skipped: list[Path] = []
    for usecase in usecase_items(manifest):
        source = required_mapping(usecase.get("source"), "usecase.source")
        contract_file = root_path / string_or_default(
            source.get("contract_file"),
            default_contract_file(usecase, contracts_root=contracts_root),
        )
        implementation_file = root_path / string_or_default(
            source.get("implementation_file"),
            default_implementation_file(usecase, implementations_root=implementations_root),
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

        if not dry_run:
            ensure_init_files(contract_file.parent, stop_at=root_path)
            if create_implementation:
                ensure_init_files(implementation_file.parent, stop_at=root_path)

    return ManifestScaffoldResult(files=tuple(created), skipped=tuple(skipped))


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
        lines.extend([f'"""{description}"""', ""])
    lines.extend(["from __future__ import annotations", ""])
    lines.extend(stdlib_import_lines(type_exprs))
    lines.append(f"from typing import {', '.join(typing_imports(type_exprs, errors))}")
    lines.extend(["", "from usecaseapi import ("])
    for import_name in usecaseapi_imports(errors):
        lines.append(f"    {import_name},")
    lines.extend([")", "", ""])

    for model in models:
        lines.extend(render_model_class(model))
        lines.append("")

    for error in errors:
        lines.extend(render_error_class(error))
        lines.append("")

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
    module_docstring = f'"""{description}"""\n\n' if isinstance(description, str) else ""
    return f'''{module_docstring}from __future__ import annotations

from {contract_module} import {input_name}, {output_name}, {protocol_class}


class {implementation_class}:
    """{class_description}"""

    async def __call__(self, input: {input_name}, /) -> {output_name}:
        """Implement {implementation_class}.__call__ before using this class."""
        raise NotImplementedError("{implementation_class}.__call__ is not implemented")


_impl: {protocol_class} = {implementation_class}()
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


def diff_manifests(old: Mapping[str, Any], new: Mapping[str, Any]) -> ManifestDiff:
    """Compare two Manifest catalogs with conservative contract checks."""
    validate_manifest(old)
    validate_manifest(new)
    old_cases = index_usecases(old)
    new_cases = index_usecases(new)
    breaking: list[str] = []
    warnings: list[str] = []
    additions: list[str] = []

    collect_added_removed(old_cases, new_cases, breaking=breaking, additions=additions)
    for key in sorted(set(old_cases) & set(new_cases)):
        collect_changed_usecase(
            key,
            old_cases[key],
            new_cases[key],
            breaking=breaking,
            warnings=warnings,
        )

    return ManifestDiff(
        breaking=tuple(breaking),
        warnings=tuple(warnings),
        additions=tuple(additions),
    )


def diff_manifest_with_api(api: UseCaseAPI[Any], manifest: Mapping[str, Any]) -> ManifestDiff:
    """Compare a Manifest file with the Manifest exported from code."""
    exported = manifest_from_api(
        api, project=project_name(manifest), package=package_name(manifest)
    )
    return diff_manifests(manifest, exported)


def collect_added_removed(
    old_cases: Mapping[str, Mapping[str, Any]],
    new_cases: Mapping[str, Mapping[str, Any]],
    *,
    breaking: list[str],
    additions: list[str],
) -> None:
    """Collect added and removed usecase keys."""
    for key in sorted(set(old_cases) - set(new_cases)):
        breaking.append(f"removed usecase {key}")
    for key in sorted(set(new_cases) - set(old_cases)):
        additions.append(f"added usecase {key}")


def collect_changed_usecase(
    key: str,
    old_case: Mapping[str, Any],
    new_case: Mapping[str, Any],
    *,
    breaking: list[str],
    warnings: list[str],
) -> None:
    """Collect semantic changes for one shared usecase."""
    if required_string(old_case, "input") != required_string(new_case, "input"):
        breaking.append(f"changed input model for {key}")
    if required_string(old_case, "output") != required_string(new_case, "output"):
        breaking.append(f"changed output model for {key}")
    if model_field_changes(old_case, new_case):
        breaking.append(f"changed model fields for {key}")
    if error_map(old_case) != error_map(new_case):
        breaking.append(f"changed errors for {key}")
    collect_removed_values(
        key,
        old_case,
        new_case,
        breaking=breaking,
        warnings=warnings,
    )
    if old_case.get("deprecated") is False and new_case.get("deprecated") is True:
        warnings.append(f"deprecated usecase {key}")


def collect_removed_values(
    key: str,
    old_case: Mapping[str, Any],
    new_case: Mapping[str, Any],
    *,
    breaking: list[str],
    warnings: list[str],
) -> None:
    """Collect removed declared errors and dependencies."""
    removed_raises = sorted(
        set(string_list(old_case.get("raises"))) - set(string_list(new_case.get("raises")))
    )
    if removed_raises:
        breaking.append(f"removed declared errors for {key}: {', '.join(removed_raises)}")
    removed_uses = sorted(
        set(string_list(old_case.get("uses"))) - set(string_list(new_case.get("uses")))
    )
    if removed_uses:
        warnings.append(f"removed declared uses for {key}: {', '.join(removed_uses)}")


def ref_to_manifest_usecase(
    ref: UseCaseRef[Any, Any],
    *,
    uses: Sequence[str],
    include_json_schema: bool,
    contracts_root: str,
    implementations_root: str,
    package: str | None,
) -> dict[str, Any]:
    """Convert one usecase reference into Manifest usecase metadata."""
    contract = ref.contract
    contract_file = source_file(ref.protocol)
    module_name = ref.protocol.__module__
    source: dict[str, Any] = {
        "contract_module": module_name,
        "protocol_class": ref.protocol.__qualname__,
        "implementation_class": default_implementation_class(contract.name),
        "implementation_file": default_implementation_path(
            contract.name,
            version=contract.version,
            implementations_root=implementations_root,
            package=package,
        ),
        "ref": find_ref_symbol(ref) or default_ref_symbol(contract.name),
    }
    if contract_file is not None:
        source["contract_file"] = trim_to_root(contract_file, contracts_root)

    item: dict[str, Any] = {
        "name": contract.name,
        "version": contract.version,
        "key": contract.key,
        "description": contract.description,
        "stable": contract.stable,
        "deprecated": contract.deprecated,
        "superseded_by": contract.superseded_by,
        "tags": list(contract.tags),
        "protocol": {
            "kind": PROTOCOL_KIND,
            "signature": (
                f"async __call__(input: {contract.input.__name__}) -> {contract.output.__name__}"
            ),
        },
        "source": source,
        "input": contract.input.__name__,
        "output": contract.output.__name__,
        "models": [
            model_to_manifest(model) for model in collect_models(contract.input, contract.output)
        ],
        "errors": [error_to_manifest(error_type) for error_type in collect_errors(contract)],
        "raises": [class_name(error_type) for error_type in contract.raises],
        "known_errors": [class_name(error_type) for error_type in contract.known_errors],
        "uses": list(uses),
    }
    if include_json_schema:
        item["schemas"] = {
            "input": contract.input.model_json_schema(),
            "output": contract.output.model_json_schema(),
        }
    return without_none(item)


def model_to_manifest(model_type: type[Model]) -> dict[str, Any]:
    """Convert a Model class into Manifest model metadata."""
    item: dict[str, Any] = {
        "name": model_type.__name__,
        "module": model_type.__module__,
        "fields": [
            field_to_manifest(name, field) for name, field in model_type.model_fields.items()
        ],
    }
    description = inspect.getdoc(model_type)
    if description is not None:
        item["description"] = description
    return item


def field_to_manifest(name: str, field: FieldInfo) -> dict[str, Any]:
    """Convert a Pydantic field into Manifest field metadata."""
    item: dict[str, Any] = {
        "name": name,
        "type": format_annotation(field.annotation),
        "required": field.is_required(),
    }
    if field.description is not None:
        item["description"] = field.description
    return item


def error_to_manifest(error_type: type[UseCaseError]) -> dict[str, Any]:
    """Convert a UseCaseError class into Manifest error metadata."""
    bases = [base for base in error_type.__bases__ if issubclass(base, UseCaseError)]
    base_name = bases[0].__name__ if bases else "UseCaseError"
    item: dict[str, Any] = {
        "name": error_type.__name__,
        "module": error_type.__module__,
        "base": base_name,
        "code": getattr(error_type, "code", ""),
        "fields": error_fields(error_type),
    }
    description = inspect.getdoc(error_type)
    if description is not None:
        item["description"] = description
    return item


def error_fields(error_type: type[UseCaseError]) -> list[dict[str, Any]]:
    """Extract public constructor and annotated fields from an error class."""
    try:
        hints = get_type_hints(error_type)
    except (NameError, TypeError):
        hints = getattr(error_type, "__annotations__", {})
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, annotation in hints.items():
        if name == "code" or get_origin(annotation) is ClassVar:
            continue
        fields.append({"name": name, "type": format_annotation(annotation), "required": True})
        seen.add(name)

    try:
        signature = inspect.signature(error_type.__init__)
        init_hints = get_type_hints(error_type.__init__)
    except (NameError, TypeError, ValueError):
        return fields
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "args", "kwargs"} or parameter.name in seen:
            continue
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue
        annotation = init_hints.get(parameter.name, parameter.annotation)
        if annotation is inspect.Signature.empty:
            continue
        fields.append(
            {
                "name": parameter.name,
                "type": format_annotation(annotation),
                "required": parameter.default is inspect.Signature.empty,
            }
        )
        seen.add(parameter.name)
    return fields


def collect_models(*roots: type[Model]) -> tuple[type[Model], ...]:
    """Collect root and nested Model classes in dependency order."""
    seen: set[type[Model]] = set()
    ordered: list[type[Model]] = []

    def visit(model_type: type[Model]) -> None:
        if model_type in seen:
            return
        seen.add(model_type)
        for field in model_type.model_fields.values():
            for nested in model_types_from_annotation(field.annotation):
                visit(nested)
        ordered.append(model_type)

    for root in roots:
        visit(root)
    return tuple(ordered)


def model_types_from_annotation(annotation: object) -> tuple[type[Model], ...]:
    """Return nested Model classes referenced by an annotation."""
    if inspect.isclass(annotation) and issubclass(annotation, Model):
        return (annotation,)
    origin = get_origin(annotation)
    if origin is None:
        return ()
    found: list[type[Model]] = []
    for arg in get_args(annotation):
        found.extend(model_types_from_annotation(arg))
    return tuple(found)


def collect_errors(contract: Any) -> tuple[type[UseCaseError], ...]:
    """Collect declared and known error classes without duplicates."""
    seen: set[type[UseCaseError]] = set()
    ordered: list[type[UseCaseError]] = []
    for error_type in (*contract.raises, *contract.known_errors):
        if error_type not in seen:
            seen.add(error_type)
            ordered.append(error_type)
    return tuple(ordered)


def format_annotation(annotation: object) -> str:
    """Render an annotation as a Manifest type expression."""
    if annotation is None or annotation is type(None):
        return "None"
    if annotation is Any:
        return "Any"
    if inspect.isclass(annotation):
        return annotation.__name__
    origin = get_origin(annotation)
    return format_origin_annotation(origin, annotation)


def format_origin_annotation(origin: object, annotation: object) -> str:
    """Render a parametrized or union annotation."""
    if origin is Literal:
        values = ", ".join(repr(arg) for arg in get_args(annotation))
        return f"Literal[{values}]"
    if origin is Union or origin is types.UnionType:
        return " | ".join(format_annotation(arg) for arg in get_args(annotation))
    if origin in (list, dict, set, tuple):
        return format_collection_annotation(origin, get_args(annotation))
    return str(annotation).replace("typing.", "")


def format_collection_annotation(origin: object, args: tuple[object, ...]) -> str:
    """Render built-in collection annotations."""
    if origin is list and args:
        return f"list[{format_annotation(args[0])}]"
    if origin is set and args:
        return f"set[{format_annotation(args[0])}]"
    if origin is dict and len(args) == 2:
        return f"dict[{format_annotation(args[0])}, {format_annotation(args[1])}]"
    if origin is tuple and args:
        return "tuple[" + ", ".join(format_annotation(arg) for arg in args) + "]"
    return str(origin).replace("typing.", "")


def validate_usecase_manifest(
    item: Mapping[str, Any],
    *,
    seen_keys: set[str],
    index: int,
) -> None:
    """Validate one Manifest usecase entry."""
    key = validate_usecase_identity(item, seen_keys=seen_keys, index=index)
    validate_source(item, index=index)
    validate_models(item, index=index)
    error_base_by_name = validate_errors(item)
    validate_error_boundaries(item, error_base_by_name)
    validate_uses(item, key=key)


def validate_usecase_identity(
    item: Mapping[str, Any],
    *,
    seen_keys: set[str],
    index: int,
) -> str:
    """Validate usecase name, version, and canonical key identity."""
    name = required_string(item, "name")
    if not valid_contract_name(name):
        raise ManifestError(f"usecases[{index}].name must look like 'package.use_case'")
    if "domain" in item:
        raise ManifestError(f"usecases[{index}].domain is not supported; use layout.package")
    version = required_int(item, "version")
    if version < 1:
        raise ManifestError(f"usecases[{index}].version must be >= 1")
    key = string_or_default(item.get("key"), f"{name}@v{version}")
    if key != f"{name}@v{version}":
        raise ManifestError(f"usecases[{index}].key must be '{name}@v{version}'")
    if key in seen_keys:
        raise ManifestError(f"duplicate usecase key {key!r}")
    seen_keys.add(key)
    return key


def validate_source(item: Mapping[str, Any], *, index: int) -> None:
    """Validate source mapping for one usecase."""
    source = required_mapping(item.get("source"), f"usecases[{index}].source")
    for field_name in ("contract_module", "protocol_class", "ref"):
        value = required_string(source, field_name)
        if field_name == "contract_module":
            if not valid_module_path(value):
                raise ManifestError(f"usecases[{index}].source.contract_module is invalid")
        elif not value.isidentifier():
            raise ManifestError(f"usecases[{index}].source.{field_name} must be an identifier")


def validate_models(item: Mapping[str, Any], *, index: int) -> None:
    """Validate model declarations for one usecase."""
    input_name = required_string(item, "input")
    output_name = required_string(item, "output")
    if not input_name.isidentifier() or not output_name.isidentifier():
        raise ManifestError(f"usecases[{index}].input/output must be identifiers")

    model_names: set[str] = set()
    for model in manifest_models(item):
        model_name = required_string(model, "name")
        if not model_name.isidentifier():
            raise ManifestError(f"model name must be an identifier: {model_name!r}")
        if model_name in model_names:
            raise ManifestError(f"duplicate model name {model_name!r}")
        model_names.add(model_name)
        for field in manifest_fields(model):
            validate_field(field, context=f"model {model_name}")
    if input_name not in model_names:
        raise ManifestError(f"input model {input_name!r} is not defined in models")
    if output_name not in model_names:
        raise ManifestError(f"output model {output_name!r} is not defined in models")


def validate_errors(item: Mapping[str, Any]) -> dict[str, str]:
    """Validate error declarations and return base metadata by name."""
    errors = manifest_errors(item)
    error_names: set[str] = {"UseCaseError"}
    error_base_by_name: dict[str, str] = {}
    for error in errors:
        error_name = required_string(error, "name")
        if not error_name.isidentifier():
            raise ManifestError(f"error name must be an identifier: {error_name!r}")
        if error_name in error_names:
            raise ManifestError(f"duplicate error name {error_name!r}")
        required_string(error, "code")
        base = string_or_default(error.get("base"), "UseCaseError")
        error_names.add(error_name)
        error_base_by_name[error_name] = base
        for field in manifest_fields(error):
            validate_field(field, context=f"error {error_name}")
    for error_name, base in error_base_by_name.items():
        if base not in error_names:
            raise ManifestError(f"error {error_name} extends unknown base {base!r}")
    return error_base_by_name


def validate_error_boundaries(
    item: Mapping[str, Any],
    error_base_by_name: Mapping[str, str],
) -> None:
    """Validate raises and known_errors against declared errors."""
    raises = string_list(item.get("raises"))
    known_errors = string_list(item.get("known_errors"))
    error_names = {"UseCaseError", *error_base_by_name}
    for name_value in (*raises, *known_errors):
        if name_value not in error_names:
            raise ManifestError(f"declared error {name_value!r} is not defined in errors")
    for known_error in known_errors:
        if raises and not any(
            error_extends(known_error, raised, error_base_by_name) for raised in raises
        ):
            raise ManifestError(f"known error {known_error!r} is not covered by raises")


def validate_uses(item: Mapping[str, Any], *, key: str) -> None:
    """Validate declared dependency keys."""
    for use_key in string_list(item.get("uses")):
        if not valid_key(use_key):
            raise ManifestError(f"invalid uses key {use_key!r}")
        if use_key == key:
            raise ManifestError(f"usecase {key!r} cannot use itself")


def validate_type_expr(expr: str) -> None:
    """Validate UseCaseAPI's Python-annotation-compatible type expression subset."""
    try:
        parsed = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ManifestError(f"invalid type expression {expr!r}") from exc
    validate_type_ast(parsed.body, expr=expr)


def validate_type_ast(node: ast.AST, *, expr: str) -> None:
    """Validate an AST node for the supported type expression subset."""
    if isinstance(node, ast.Name):
        if not (node.id in _BUILTIN_TYPE_NAMES or node.id.isidentifier()):
            raise ManifestError(f"invalid type name in {expr!r}: {node.id!r}")
        return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str | int | float | bool) or node.value is None:
            return
        raise ManifestError(f"invalid literal in {expr!r}")
    if isinstance(node, ast.Subscript):
        validate_type_ast(node.value, expr=expr)
        validate_type_ast(node.slice, expr=expr)
        return
    if isinstance(node, ast.Tuple | ast.List):
        for element in node.elts:
            validate_type_ast(element, expr=expr)
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        validate_type_ast(node.left, expr=expr)
        validate_type_ast(node.right, expr=expr)
        return
    raise ManifestError(f"unsupported type expression syntax in {expr!r}")


def validate_field(field: Mapping[str, Any], *, context: str) -> None:
    """Validate one Manifest model or error field."""
    field_name = required_string(field, "name")
    if not field_name.isidentifier():
        raise ManifestError(f"{context} field name must be an identifier: {field_name!r}")
    validate_type_expr(required_string(field, "type"))
    required = field.get("required", True)
    if not isinstance(required, bool):
        raise ManifestError(f"{context}.{field_name}.required must be a boolean")


def manifest_models(usecase: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read Manifest model mappings."""
    value = usecase.get("models")
    if not isinstance(value, list) or not value:
        raise ManifestError("usecase.models must be a non-empty list")
    return [required_mapping(item, "model") for item in value]


def manifest_errors(usecase: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read Manifest error mappings."""
    value = usecase.get("errors", [])
    if not isinstance(value, list):
        raise ManifestError("usecase.errors must be a list")
    return [required_mapping(item, "error") for item in value]


def manifest_fields(container: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read Manifest field mappings."""
    value = container.get("fields", [])
    if not isinstance(value, list):
        raise ManifestError("fields must be a list")
    return [required_mapping(item, "field") for item in value]


def usecase_items(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read Manifest usecase mappings."""
    value = manifest.get("usecases")
    if not isinstance(value, list):
        raise ManifestError("manifest.usecases must be a list")
    return [required_mapping(item, "usecase") for item in value]


def render_model_class(model: Mapping[str, Any]) -> list[str]:
    """Render a Model class from Manifest metadata."""
    name = required_string(model, "name")
    fields = manifest_fields(model)
    lines = [f"class {name}(Model):"]
    description = model.get("description")
    if isinstance(description, str) and description:
        lines.append(f'    """{description}"""')
        lines.append("")
    if not fields:
        lines.append("    pass")
        return lines
    for field in fields:
        required = bool(field.get("required", True))
        type_expr = required_string(field, "type")
        if not required and "None" not in type_expr:
            type_expr = f"{type_expr} | None"
        default = "" if required else " = None"
        lines.append(f"    {required_string(field, 'name')}: {type_expr}{default}")
    return lines


def render_error_class(error: Mapping[str, Any]) -> list[str]:
    """Render a UseCaseError class from Manifest metadata."""
    name = required_string(error, "name")
    base = string_or_default(error.get("base"), "UseCaseError")
    code = required_string(error, "code")
    fields = manifest_fields(error)
    lines = [f"class {name}({base}):", f'    code: ClassVar[str] = "{code}"']
    if not fields:
        return lines
    lines.append("")
    for field in fields:
        lines.append(f"    {required_string(field, 'name')}: {required_string(field, 'type')}")
    lines.append("")
    params = ", ".join(
        f"{required_string(field, 'name')}: {required_string(field, 'type')}" for field in fields
    )
    lines.append(f"    def __init__(self, *, {params}) -> None:")
    for field in fields:
        field_name = required_string(field, "name")
        lines.append(f"        self.{field_name} = {field_name}")
    lines.append(f'        super().__init__("{code}")')
    return lines


def collect_type_exprs(
    models: Sequence[Mapping[str, Any]],
    errors: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Collect all field type expressions used by generated code."""
    exprs: list[str] = []
    for container in (*models, *errors):
        for field in manifest_fields(container):
            exprs.append(required_string(field, "type"))
    return exprs


def typing_imports(
    type_exprs: Sequence[str],
    errors: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Return typing imports required by generated code."""
    imports = ["Protocol"]
    if errors:
        imports.append("ClassVar")
    if any("Literal[" in expr for expr in type_exprs):
        imports.append("Literal")
    if any(type_expr_contains_name(expr, "Any") for expr in type_exprs):
        imports.append("Any")
    return sorted(set(imports))


def usecaseapi_imports(errors: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return usecaseapi imports required by generated code."""
    imports = ["Contract", "Model", "UseCase", "UseCaseRef", "define_usecase"]
    if errors:
        imports.insert(3, "UseCaseError")
    return imports


def render_contract_binding(
    *,
    protocol_class: str,
    input_name: str,
    output_name: str,
    ref: str,
    name: str,
    version: int,
    raises: Sequence[str],
    known_errors: Sequence[str],
    stable: bool,
    deprecated: bool,
    superseded_by: object,
    description: object,
    tags: Sequence[str],
) -> list[str]:
    """Render protocol and UseCaseRef binding code."""
    protocol_description = (
        description
        if isinstance(description, str)
        else (f"Contract Protocol for {name} v{version}.")
    )
    lines = [
        f"class {protocol_class}(UseCase[{input_name}, {output_name}], Protocol):",
        f'    """{protocol_description}"""',
        "",
        f"    async def __call__(self, input: {input_name}, /) -> {output_name}:",
        "        ...",
        "",
        "",
        f"{ref}: UseCaseRef[{input_name}, {output_name}] = define_usecase(",
        f"    {protocol_class},",
        "    Contract(",
        f'        name="{name}",',
        f"        version={version},",
        f"        input={input_name},",
        f"        output={output_name},",
        f"        raises={tuple_expr(raises)},",
        f"        known_errors={tuple_expr(known_errors)},",
        f"        stable={stable!r},",
        f"        deprecated={deprecated!r},",
    ]
    lines.extend(optional_contract_metadata_lines(superseded_by, description, tags))
    lines.extend(["    ),", ")", ""])
    return lines


def optional_contract_metadata_lines(
    superseded_by: object,
    description: object,
    tags: Sequence[str],
) -> list[str]:
    """Render optional Contract keyword lines."""
    lines: list[str] = []
    if isinstance(superseded_by, str):
        lines.append(f"        superseded_by={superseded_by!r},")
    if isinstance(description, str):
        lines.append(f"        description={description!r},")
    if tags:
        lines.append(f"        tags={tuple(tags)!r},")
    return lines


def stdlib_import_lines(type_exprs: Sequence[str]) -> list[str]:
    """Render standard-library imports required by type expressions."""
    lines: list[str] = []
    if any(type_expr_contains_name(expr, "UUID") for expr in type_exprs):
        lines.append("from uuid import UUID")
    datetime_names = [
        name
        for name in ("date", "datetime")
        if any(type_expr_contains_name(expr, name) for expr in type_exprs)
    ]
    if datetime_names:
        lines.append("from datetime import " + ", ".join(sorted(set(datetime_names))))
    if any(type_expr_contains_name(expr, "Decimal") for expr in type_exprs):
        lines.append("from decimal import Decimal")
    if lines:
        lines.append("")
    return lines


def type_expr_contains_name(expr: str, name: str) -> bool:
    """Return whether a type expression references a name."""
    try:
        parsed = ast.parse(expr, mode="eval")
    except SyntaxError:
        return False
    return any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(parsed))


def tuple_expr(names: Sequence[str]) -> str:
    """Render names as a Python tuple expression."""
    if not names:
        return "()"
    return "(" + ", ".join(names) + ",)"


def default_contract_file(usecase: Mapping[str, Any], *, contracts_root: str) -> str:
    """Return the default generated contract file path."""
    name = required_string(usecase, "name")
    version = required_int(usecase, "version")
    parts = name.split(".")
    return str(Path(contracts_root) / Path(*parts[:-1]) / parts[-1] / f"v{version}.py")


def default_implementation_file(usecase: Mapping[str, Any], *, implementations_root: str) -> str:
    """Return the default generated implementation file path."""
    name = required_string(usecase, "name")
    parts = name.split(".")
    return str(Path(implementations_root) / Path(*parts[:-1]) / f"{parts[-1]}.py")


def default_implementation_class(name: str) -> str:
    """Return the default v1.1 implementation class name for exported source metadata."""
    return "".join(part.capitalize() for part in name.split(".")[-1].split("_")) + "UseCase"


def default_implementation_path(
    name: str,
    *,
    version: int,
    implementations_root: str,
    package: str | None,
) -> str:
    """Return the default implementation path for exported source metadata."""
    parts = name.split(".")
    if package is not None and parts[0] == package:
        package_name = package
        usecase_parts = parts[1:]
    else:
        package_name = parts[0]
        usecase_parts = parts[1:]
    usecase_name = parts[-1]
    return str(
        Path(implementations_root)
        / package_name
        / "usecases"
        / Path(*usecase_parts)
        / f"v{version}"
        / f"{usecase_name}_usecase.py"
    )


def write_generated_file(path: Path, content: str, *, force: bool, dry_run: bool) -> None:
    """Write a generated file unless dry-run or protected by force."""
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass force=True to overwrite")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def ensure_init_files(directory: Path, *, stop_at: Path) -> None:
    """Create package __init__.py files up to a boundary."""
    current = directory
    stop = stop_at.resolve()
    while True:
        if current.resolve() == stop or current.parent == current:
            break
        init_file = current / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")
        current = current.parent


def source_file(value: Any) -> str | None:
    """Return a source file path for an inspected object when available."""
    try:
        file_name = inspect.getsourcefile(value)
    except TypeError:
        return None
    if file_name is None:
        return None
    path = Path(file_name).resolve()
    try:
        return path.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def trim_to_root(file_path: str, root: str) -> str:
    """Trim a source path so it starts at the configured root."""
    path_parts = Path(file_path).parts
    root_parts = Path(root).parts
    if not root_parts:
        return file_path
    for index in range(0, len(path_parts) - len(root_parts) + 1):
        if path_parts[index : index + len(root_parts)] == root_parts:
            return str(Path(*path_parts[index:]))
    return file_path


def qualname(value: object) -> str:
    """Return a stable module-qualified name when available."""
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        return f"{module}.{qualname}"
    return repr(value)


def find_ref_symbol(ref: UseCaseRef[Any, Any]) -> str | None:
    """Find the symbol name that exports a UseCaseRef."""
    module = sys.modules.get(ref.protocol.__module__)
    if module is None:
        return None
    for name, value in vars(module).items():
        if value is ref and name.isidentifier():
            return name
    return None


def default_ref_symbol(name: str) -> str:
    """Return the default constant name for a contract."""
    return name.split(".")[-1].upper()


def class_name(error_type: type[UseCaseError]) -> str:
    """Return the class name for an error type."""
    return error_type.__name__


def valid_contract_name(name: str) -> bool:
    """Return whether a contract name is valid."""
    parts = name.split(".")
    return len(parts) >= 2 and all(part.isidentifier() and part.islower() for part in parts)


def valid_key(key: str) -> bool:
    """Return whether a usecase key is valid."""
    if "@v" not in key:
        return False
    name, _, version = key.partition("@v")
    return valid_contract_name(name) and version.isdigit() and int(version) >= 1


def valid_module_path(value: str) -> bool:
    """Return whether a dotted Python module path is valid."""
    return bool(value) and all(part.isidentifier() for part in value.split("."))


def error_extends(error_name: str, base_name: str, base_by_name: Mapping[str, str]) -> bool:
    """Return whether one error extends another by Manifest metadata."""
    current = error_name
    while current != "UseCaseError":
        if current == base_name:
            return True
        current = base_by_name.get(current, "UseCaseError")
    return base_name == "UseCaseError"


def required_string(mapping: Mapping[str, Any], key: str) -> str:
    """Read a required non-empty string field."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{key} must be a non-empty string")
    return value


def required_int(mapping: Mapping[str, Any], key: str) -> int:
    """Read a required integer field."""
    value = mapping.get(key)
    if not isinstance(value, int):
        raise ManifestError(f"{key} must be an integer")
    return value


def string_or_default(value: object, default: str) -> str:
    """Read a non-empty string or return a default."""
    return value if isinstance(value, str) and value else default


def string_list(value: object) -> list[str]:
    """Read a list of strings, rejecting malformed values."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestError("expected a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ManifestError("expected a list of strings")
        result.append(item)
    return result


def required_mapping(value: object, name: str) -> Mapping[str, Any]:
    """Read a required mapping value."""
    if not isinstance(value, Mapping):
        raise ManifestError(f"{name} must be a mapping")
    return value


def without_none(value: dict[str, Any]) -> dict[str, Any]:
    """Return a copy without None values, including nested mappings."""
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            nested = without_none(item)
            if nested:
                result[key] = nested
        elif item is not None:
            result[key] = item
    return result


def usecase_key(usecase: Mapping[str, Any]) -> str:
    """Return the canonical key for a Manifest usecase."""
    return string_or_default(
        usecase.get("key"),
        f"{required_string(usecase, 'name')}@v{required_int(usecase, 'version')}",
    )


def node_id(key: str) -> str:
    """Return a Mermaid-safe node identifier."""
    return "uc_" + "".join(character if character.isalnum() else "_" for character in key)


def index_usecases(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Index Manifest usecases by key."""
    return {usecase_key(item): item for item in usecase_items(manifest)}


def model_map(usecase: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return comparable model field metadata keyed by model name."""
    return {
        required_string(model, "name"): [
            dict(field)
            for field in sorted(
                manifest_fields(model), key=lambda field: required_string(field, "name")
            )
        ]
        for model in manifest_models(usecase)
    }


def error_map(usecase: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return comparable error metadata keyed by error name."""
    return {
        required_string(error, "name"): {
            "base": string_or_default(error.get("base"), "UseCaseError"),
            "code": required_string(error, "code"),
            "fields": [
                dict(field)
                for field in sorted(
                    manifest_fields(error), key=lambda field: required_string(field, "name")
                )
            ],
        }
        for error in manifest_errors(usecase)
    }


def model_field_changes(old_case: Mapping[str, Any], new_case: Mapping[str, Any]) -> bool:
    """Return whether model names or fields changed."""
    old_models = model_map(old_case)
    new_models = model_map(new_case)
    for name, old_fields in old_models.items():
        if name in {
            required_string(old_case, "input"),
            required_string(old_case, "output"),
        } and (name not in new_models or new_models[name] != old_fields):
            return True
    return False


def semantic_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the semantic subset used for sync comparison."""
    validate_manifest(manifest)
    return {
        "kind": MANIFEST_KIND,
        "usecases": [
            {
                "name": required_string(item, "name"),
                "version": required_int(item, "version"),
                "key": usecase_key(item),
                "description": item.get("description"),
                "stable": item.get("stable", True),
                "deprecated": item.get("deprecated", False),
                "superseded_by": item.get("superseded_by"),
                "tags": string_list(item.get("tags")),
                "input": required_string(item, "input"),
                "output": required_string(item, "output"),
                "models": model_map(item),
                "errors": error_map(item),
                "raises": string_list(item.get("raises")),
                "known_errors": string_list(item.get("known_errors")),
                "uses": string_list(item.get("uses")),
            }
            for item in usecase_items(manifest)
        ],
    }


def project_name(manifest: Mapping[str, Any]) -> str | None:
    """Read Manifest project name when present."""
    metadata = manifest.get("metadata")
    name = metadata.get("name") if isinstance(metadata, Mapping) else None
    if isinstance(name, str):
        return name
    return None


def package_name(manifest: Mapping[str, Any]) -> str | None:
    """Read Manifest package name when present."""
    layout = manifest.get("layout")
    package = layout.get("package") if isinstance(layout, Mapping) else None
    if isinstance(package, str):
        return package
    return None
