"""Read normalized Manifest collections."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .common import *
from .helpers import *


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
    if manifest.get("kind") == LEGACY_MANIFEST_KIND or "usecases" in manifest:
        value = manifest.get("usecases")
    else:
        from .validation import semantic_from_openapi_manifest

        value = semantic_from_openapi_manifest(manifest).get("usecases")
    if not isinstance(value, list):
        raise ManifestError("manifest.usecases must be a list")
    return [required_mapping(item, "usecase") for item in value]


def usecase_items_from_semantic(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read already-normalized semantic usecase mappings."""
    value = manifest.get("usecases")
    if not isinstance(value, list):
        raise ManifestError("manifest.usecases must be a list")
    return [required_mapping(item, "usecase") for item in value]


__all__ = [name for name in globals() if not name.startswith("__")]
