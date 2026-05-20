"""Semantic Manifest comparison and project metadata helpers."""

from __future__ import annotations

import ast

from collections.abc import Mapping, Sequence
from typing import Any

from usecaseapi.manifest_domain.common import (
    LEGACY_MANIFEST_KIND,
    OPENAPI_VERSION,
)
from usecaseapi.manifest_domain.semantic.accessors import (
    manifest_errors,
    manifest_fields,
    manifest_models,
    usecase_items,
)
from usecaseapi.manifest_domain.shared.helpers import (
    required_int,
    required_string,
    string_list,
    string_or_default,
)


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
    for name in reachable_model_names(old_case, old_models):
        old_fields = old_models[name]
        if name not in new_models or new_models[name] != old_fields:
            return True
    return False


def reachable_model_names(
    usecase: Mapping[str, Any],
    models: Mapping[str, Sequence[Mapping[str, Any]]],
) -> set[str]:
    """Return model names reachable from the input and output contract boundary."""
    pending = [required_string(usecase, "input"), required_string(usecase, "output")]
    for error in manifest_errors(usecase):
        for field in manifest_fields(error):
            pending.extend(model_names_from_type_expr(required_string(field, "type"), models))
    reachable: set[str] = set()
    while pending:
        name = pending.pop()
        if name in reachable or name not in models:
            continue
        reachable.add(name)
        for field in models[name]:
            pending.extend(model_names_from_type_expr(required_string(field, "type"), models))
    return reachable


def model_names_from_type_expr(
    expr: str,
    models: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[str, ...]:
    """Return manifest model names referenced by a supported type expression."""
    parsed = ast.parse(expr, mode="eval").body
    found: list[str] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            if node.id in models:
                found.append(node.id)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(parsed)
    return tuple(found)


def semantic_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the semantic subset used for sync comparison."""
    from usecaseapi.manifest_domain.io import validate_manifest

    validate_manifest(manifest)
    return {
        "kind": LEGACY_MANIFEST_KIND,
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
    if manifest.get("openapi") == OPENAPI_VERSION:
        info = manifest.get("info")
        name = info.get("title") if isinstance(info, Mapping) else None
    else:
        name = project_name_from_semantic(manifest)
    if isinstance(name, str):
        return name
    return None


def project_name_from_semantic(manifest: Mapping[str, Any]) -> str | None:
    """Read semantic Manifest project name when present."""
    metadata = manifest.get("metadata")
    name = metadata.get("name") if isinstance(metadata, Mapping) else None
    if isinstance(name, str):
        return name
    return None


def package_name(manifest: Mapping[str, Any]) -> str | None:
    """Read Manifest package name when present."""
    if manifest.get("openapi") == OPENAPI_VERSION:
        from usecaseapi.manifest_domain.openapi.usecase_projection import (
            semantic_from_openapi_manifest,
        )

        layout = semantic_from_openapi_manifest(manifest).get("layout")
    else:
        layout = manifest.get("layout")
    package = layout.get("package") if isinstance(layout, Mapping) else None
    if isinstance(package, str):
        return package
    return None
