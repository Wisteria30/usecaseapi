"""Code-first Manifest export and diff support."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from usecaseapi.api import UseCaseAPI

from .code_first_types import *
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


__all__ = [name for name in globals() if not name.startswith("__")]
