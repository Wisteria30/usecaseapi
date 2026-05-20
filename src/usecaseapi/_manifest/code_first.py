"""Manifest implementation package."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

import inspect
import types

from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar, Literal, Union, cast, get_args, get_origin, get_type_hints

from pydantic.fields import FieldInfo

from usecaseapi.api import UseCaseAPI
from usecaseapi.contracts import UseCaseRef
from usecaseapi.errors import UseCaseError
from usecaseapi.model import Model

from .common import *
from .openapi import *
from .validation import *


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

    legacy_manifest: dict[str, Any] = {
        "kind": LEGACY_MANIFEST_KIND,
        "metadata": {"name": project or "usecaseapi-project"},
        "runtime": {
            "language": "python",
            "python": ">=3.12,<3.15",
            "protocol": LEGACY_PROTOCOL_KIND,
        },
        "layout": layout,
        "usecases": usecases,
    }
    manifest = openapi_manifest_from_semantic(legacy_manifest)
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


def diff_manifest_with_api(api: UseCaseAPI[Any], manifest: Mapping[str, Any]) -> ManifestDiff:
    """Compare a Manifest file with the Manifest exported from code."""
    from .contract_check import diff_manifests

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
    collect_declared_value_changes(
        key,
        old_case,
        new_case,
        breaking=breaking,
        warnings=warnings,
    )
    if old_case.get("deprecated") is False and new_case.get("deprecated") is True:
        warnings.append(f"deprecated usecase {key}")


def collect_declared_value_changes(
    key: str,
    old_case: Mapping[str, Any],
    new_case: Mapping[str, Any],
    *,
    breaking: list[str],
    warnings: list[str],
) -> None:
    """Collect declared error and dependency boundary changes."""
    collect_declared_set_change(
        key,
        old_case,
        new_case,
        field="raises",
        label="declared errors",
        removed_target=breaking,
        added_target=warnings,
    )
    collect_declared_set_change(
        key,
        old_case,
        new_case,
        field="known_errors",
        label="known errors",
        removed_target=breaking,
        added_target=warnings,
    )
    collect_declared_set_change(
        key,
        old_case,
        new_case,
        field="uses",
        label="declared uses",
        removed_target=warnings,
        added_target=warnings,
    )


def collect_declared_set_change(
    key: str,
    old_case: Mapping[str, Any],
    new_case: Mapping[str, Any],
    *,
    field: str,
    label: str,
    removed_target: list[str],
    added_target: list[str],
) -> None:
    """Collect set-like declared boundary changes for one usecase field."""
    old_values = set(string_list(old_case.get(field)))
    new_values = set(string_list(new_case.get(field)))
    removed_values = sorted(old_values - new_values)
    if removed_values:
        removed_target.append(f"removed {label} for {key}: {', '.join(removed_values)}")
    added_values = sorted(new_values - old_values)
    if added_values:
        added_target.append(f"added {label} for {key}: {', '.join(added_values)}")


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
    validate_representable_model(model_type)
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


def validate_representable_model(model_type: type[Model]) -> None:
    """Reject Pydantic model behavior the Manifest cannot preserve."""
    base_config = dict(Model.model_config)
    model_config = dict(model_type.model_config)
    if model_config != base_config:
        raise ManifestError(
            f"model {model_type.__qualname__!r} uses unsupported Pydantic model_config"
        )
    decorators = getattr(model_type, "__pydantic_decorators__", None)
    if decorators is None:
        return
    unsupported_decorators = {
        "validators": getattr(decorators, "validators", None),
        "field_validators": getattr(decorators, "field_validators", None),
        "root_validators": getattr(decorators, "root_validators", None),
        "model_validators": getattr(decorators, "model_validators", None),
        "field_serializers": getattr(decorators, "field_serializers", None),
        "model_serializers": getattr(decorators, "model_serializers", None),
        "computed_fields": getattr(decorators, "computed_fields", None),
    }
    present = sorted(name for name, values in unsupported_decorators.items() if values)
    if present:
        raise ManifestError(
            f"model {model_type.__qualname__!r} uses unsupported Pydantic decorators: {present!r}"
        )


def field_to_manifest(name: str, field: FieldInfo) -> dict[str, Any]:
    """Convert a Pydantic field into Manifest field metadata."""
    validate_representable_field(name, field)
    item: dict[str, Any] = {
        "name": name,
        "type": format_annotation(field.annotation),
        "required": field.is_required(),
    }
    if field.description is not None:
        item["description"] = field.description
    return item


def validate_representable_field(name: str, field: FieldInfo) -> None:
    """Reject Pydantic field metadata that the Manifest cannot preserve."""
    aliases = {
        "alias": field.alias,
        "validation_alias": field.validation_alias,
        "serialization_alias": field.serialization_alias,
    }
    for alias_name, alias_value in aliases.items():
        if alias_value is not None and alias_value != name:
            raise ManifestError(f"field {name!r} uses unsupported Pydantic {alias_name}")
    if field.default_factory is not None:
        raise ManifestError(f"field {name!r} uses an unsupported default_factory")
    if not field.is_required() and field.default is not None:
        raise ManifestError(f"field {name!r} uses an unsupported non-None default")
    if field.metadata:
        raise ManifestError(f"field {name!r} uses unsupported Pydantic constraints")
    if field.json_schema_extra is not None:
        raise ManifestError(f"field {name!r} uses unsupported JSON Schema extras")
    if field.title is not None:
        raise ManifestError(f"field {name!r} uses an unsupported schema title")
    if field.examples is not None:
        raise ManifestError(f"field {name!r} uses unsupported schema examples")
    if field.deprecated is not None:
        raise ManifestError(f"field {name!r} uses unsupported deprecation metadata")


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
