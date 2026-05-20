"""Manifest YAML IO and validation public facade."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from usecaseapi.manifest_domain.common import (
    LEGACY_MANIFEST_KIND,
    ManifestError,
)
from usecaseapi.manifest_domain.openapi.profile_validation import (
    validate_openapi_manifest,
    validate_semantic_manifest,
)
from usecaseapi.manifest_domain.openapi.usecase_projection import semantic_from_openapi_manifest


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
    if manifest.get("kind") == LEGACY_MANIFEST_KIND:
        validate_semantic_manifest(manifest)
        return
    if "kind" in manifest:
        raise ManifestError(f"manifest kind must be {LEGACY_MANIFEST_KIND!r}")
    validate_openapi_manifest(manifest)
    semantic = semantic_from_openapi_manifest(manifest)
    validate_semantic_manifest(semantic)
