"""Manifest implementation package."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

import yaml

from usecaseapi.api import UseCaseAPI

from .code_first import *
from .common import *
from .openapi import *
from .validation import *


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


def run_contract_check(
    *,
    target: str,
    manifest_path: Path,
    base_manifest_path: Path | None,
    api: UseCaseAPI[Any] | None,
    target_error: str | None = None,
) -> ContractCheckReport:
    """Validate one committed manifest against code and an optional base manifest."""
    errors: list[str] = []
    guard: ManifestGuardReport | None = None
    manifest_valid = False
    synchronized = False
    manifest_label = str(manifest_path)

    if not manifest_path.exists():
        return ContractCheckReport(
            manifest=manifest_label,
            target=target,
            manifest_valid=False,
            synchronized=False,
            guard=None,
            errors=(f"manifest not found: {manifest_path}",),
        )

    try:
        head_manifest = load_manifest(manifest_path)
    except (ManifestError, yaml.YAMLError) as exc:
        return ContractCheckReport(
            manifest=manifest_label,
            target=target,
            manifest_valid=False,
            synchronized=False,
            guard=None,
            errors=(f"manifest validation failed: {exc}",),
        )
    manifest_valid = True

    if api is None:
        errors.append(target_error or "target API could not be loaded")
    else:
        sync_diff = diff_manifest_with_api(api, head_manifest)
        sync_errors = contract_check_sync_errors(sync_diff)
        if sync_errors:
            errors.extend(sync_errors)
        else:
            synchronized = True

    if base_manifest_path is not None:
        if not base_manifest_path.exists():
            errors.append(f"base manifest not found: {base_manifest_path}")
        else:
            try:
                base_payload = yaml.safe_load(base_manifest_path.read_text())
                if not isinstance(base_payload, dict):
                    raise ManifestError("manifest must be a YAML mapping")
                base_manifest: Mapping[str, Any] = dict(base_payload)
                base_manifest = normalize_contract_check_base_manifest(base_manifest)
                guard = guard_manifests(base_manifest, head_manifest)
            except (ManifestError, yaml.YAMLError) as exc:
                errors.append(f"base manifest validation failed: {exc}")

    return ContractCheckReport(
        manifest=manifest_label,
        target=target,
        manifest_valid=manifest_valid,
        synchronized=synchronized,
        guard=guard,
        errors=tuple(errors),
    )


def normalize_contract_check_base_manifest(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Normalize historical generated base manifests for CI-only contract comparison."""
    if manifest.get("openapi") != OPENAPI_VERSION:
        return manifest
    normalized = deepcopy(manifest)
    components = normalized.get("components")
    schemas = components.get("schemas") if isinstance(components, Mapping) else None
    if not isinstance(schemas, dict):
        return normalized
    for schema in schemas.values():
        if (
            isinstance(schema, dict)
            and schema.get("type") == "object"
            and schema.get("additionalProperties") is False
            and schema.get("required") == []
            and "properties" not in schema
        ):
            schema["properties"] = {}
    return normalized


def contract_check_sync_errors(diff: ManifestDiff) -> tuple[str, ...]:
    """Return human-readable synchronization errors from a Manifest diff."""
    return tuple(
        [f"breaking: {item}" for item in diff.breaking]
        + [f"warning: {item}" for item in diff.warnings]
        + [f"addition: {item}" for item in diff.additions]
    )


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
        failures.extend(f"`{item}` was removed." for item in report.guard.removed)
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
    if additions:
        for item in additions:
            lines.append(f"- `{item}`")
    else:
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


def immutable_usecase_index(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return normalized operation contracts keyed by name and version."""
    result: dict[str, dict[str, Any]] = {}
    paths = required_mapping(manifest.get("paths"), "paths")
    for path, path_item in paths.items():
        if not isinstance(path_item, Mapping):
            continue
        post = path_item.get("post")
        if not isinstance(post, Mapping):
            continue
        extension = post.get("x-usecaseapi")
        if not isinstance(extension, Mapping) or extension.get("kind") != "usecase":
            continue
        name = required_string(extension, "name")
        version = required_int(extension, "version")
        identity = f"{name}@v{version}"
        result[identity] = normalize_immutable_operation(
            manifest=manifest,
            path=str(path),
            operation=post,
        )
    return result


def normalize_immutable_operation(
    *,
    manifest: Mapping[str, Any],
    path: str,
    operation: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the operation data that must not change for an existing version."""
    root_extension = required_mapping(manifest.get("x-usecaseapi"), "x-usecaseapi")
    component_refs = _reachable_component_refs(manifest=manifest, operation=operation)
    normalized = sort_json_like(
        {
            "path": path,
            "method": "post",
            "operation": operation,
            "components": _referenced_components(manifest=manifest, refs=component_refs),
            "x-usecaseapi-errors": _referenced_error_metadata(
                root_extension=root_extension,
                refs=component_refs,
            ),
        }
    )
    return cast(dict[str, Any], normalized)


def _reachable_component_refs(
    *,
    manifest: Mapping[str, Any],
    operation: Mapping[str, Any],
) -> set[tuple[str, str]]:
    """Return OpenAPI component references reachable from one operation."""
    components = required_mapping(manifest.get("components"), "components")
    pending = _local_component_refs(operation)
    seen: set[tuple[str, str]] = set()
    while pending:
        section, name = pending.pop()
        seen.add((section, name))
        section_value = required_mapping(components.get(section), f"components.{section}")
        component = required_mapping(section_value.get(name), f"components.{section}.{name}")
        pending.update(_local_component_refs(component) - seen)
    return seen


def _referenced_components(
    *,
    manifest: Mapping[str, Any],
    refs: set[tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    """Return OpenAPI components selected by local component references."""
    components = required_mapping(manifest.get("components"), "components")
    result: dict[str, dict[str, Any]] = {}
    for section, name in sorted(refs):
        section_value = required_mapping(components.get(section), f"components.{section}")
        component = required_mapping(section_value.get(name), f"components.{section}.{name}")
        result.setdefault(section, {})[name] = dict(component)
    return result


def _referenced_error_metadata(
    *,
    root_extension: Mapping[str, Any],
    refs: set[tuple[str, str]],
) -> dict[str, Any]:
    """Return root error metadata referenced by one operation."""
    extension_components = root_extension.get("components")
    if not isinstance(extension_components, Mapping):
        return {}
    errors = extension_components.get("errors")
    if not isinstance(errors, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key, value in errors.items():
        if isinstance(value, Mapping) and _local_component_refs(value) & refs:
            result[str(key)] = dict(value)
    return result


def _local_component_refs(value: Any) -> set[tuple[str, str]]:
    """Return local OpenAPI component references found in a JSON-like value."""
    refs: set[tuple[str, str]] = set()
    if isinstance(value, Mapping):
        ref = value.get("$ref")
        if isinstance(ref, str):
            component_ref = _local_component_ref_from_string(ref)
            if component_ref is not None:
                refs.add(component_ref)
        for item in value.values():
            refs.update(_local_component_refs(item))
    elif isinstance(value, list | tuple):
        for item in value:
            refs.update(_local_component_refs(item))
    elif isinstance(value, str):
        component_ref = _local_component_ref_from_string(value)
        if component_ref is not None:
            refs.add(component_ref)
    return refs


def _local_component_ref_from_string(value: str) -> tuple[str, str] | None:
    """Parse a local OpenAPI component reference string."""
    prefix = "#/components/"
    if not value.startswith(prefix):
        return None
    parts = value.removeprefix(prefix).split("/", 1)
    if len(parts) != 2 or not all(parts):
        return None
    return parts[0], parts[1]


def sort_json_like(value: Any) -> Any:
    """Recursively sort JSON-like values for stable semantic comparison."""
    if isinstance(value, Mapping):
        return {str(key): sort_json_like(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [sort_json_like(item) for item in value]
    if isinstance(value, tuple):
        return [sort_json_like(item) for item in value]
    return value
