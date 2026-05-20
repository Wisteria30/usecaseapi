"""Validation for the UseCaseAPI OpenAPI profile envelope."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from usecaseapi.manifest_domain.common import (
    _OPENAPI_COMPONENT_KEYS,
    _OPENAPI_JSON_SCHEMA_DIALECT,
    _OPENAPI_ROOT_EXTENSION_COMPONENT_KEYS,
    _OPENAPI_ROOT_EXTENSION_KEYS,
    _OPENAPI_ROOT_KEYS,
    _OPENAPI_RUNTIME_KEYS,
    _OPENAPI_RUNTIME_ROOT_KEYS,
    MANIFEST_PROFILE_KIND,
    OPENAPI_VERSION,
    PROTOCOL_KIND,
    USECASEAPI_PROFILE,
    USECASEAPI_VERSION,
    ManifestError,
)
from usecaseapi.manifest_domain.semantic.validation import validate_usecase_manifest
from usecaseapi.manifest_domain.shared.helpers import (
    required_mapping,
    required_string,
)


def validate_openapi_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate the OpenAPI-level v2 Manifest shape."""
    unsupported_root_keys = set(manifest) - _OPENAPI_ROOT_KEYS
    if unsupported_root_keys:
        raise ManifestError(f"OpenAPI root has unsupported keys: {sorted(unsupported_root_keys)!r}")
    if manifest.get("openapi") != OPENAPI_VERSION:
        raise ManifestError(f"manifest.openapi must be {OPENAPI_VERSION!r}")
    if manifest.get("jsonSchemaDialect") != _OPENAPI_JSON_SCHEMA_DIALECT:
        raise ManifestError(f"manifest.jsonSchemaDialect must be {_OPENAPI_JSON_SCHEMA_DIALECT!r}")
    if manifest.get("security") != []:
        raise ManifestError("manifest.security must be an empty list")
    validate_openapi_servers(manifest.get("servers"))
    validate_openapi_tags(manifest.get("tags"))
    info = required_mapping(manifest.get("info"), "info")
    required_string(info, "title")
    required_string(info, "version")
    paths = manifest.get("paths")
    components = manifest.get("components")
    if not isinstance(paths, Mapping) and not isinstance(components, Mapping):
        raise ManifestError("manifest must define OpenAPI paths or components")
    validate_openapi_components_shape(components)
    extension = required_mapping(manifest.get("x-usecaseapi"), "x-usecaseapi")
    if extension.get("version") != USECASEAPI_VERSION:
        raise ManifestError(f"x-usecaseapi.version must be {USECASEAPI_VERSION!r}")
    if extension.get("profile") != USECASEAPI_PROFILE:
        raise ManifestError(f"x-usecaseapi.profile must be {USECASEAPI_PROFILE!r}")
    if extension.get("manifestKind") != MANIFEST_PROFILE_KIND:
        raise ManifestError(f"x-usecaseapi.manifestKind must be {MANIFEST_PROFILE_KIND!r}")
    validate_openapi_root_extension_shape(extension)


def validate_openapi_servers(value: object) -> None:
    """Validate the root servers list cannot carry hidden transport contract changes."""
    if value != [
        {
            "url": "http://localhost",
            "description": (
                "Optional UseCaseAPI HTTP adapter base URL. Native UseCaseAPI calls "
                "are same-process and do not require this transport."
            ),
        }
    ]:
        raise ManifestError("manifest.servers must match the UseCaseAPI OpenAPI profile")


def validate_openapi_tags(value: object) -> None:
    """Validate root tags stay in the generated profile shape."""
    if not isinstance(value, list):
        raise ManifestError("manifest.tags must be a list")
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise ManifestError(f"manifest.tags[{index}] must be a mapping")
        unsupported_keys = set(item) - {"name"}
        if unsupported_keys:
            raise ManifestError(
                f"manifest.tags[{index}] has unsupported keys: {sorted(unsupported_keys)!r}"
            )
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ManifestError(f"manifest.tags[{index}].name must be a non-empty string")


def validate_openapi_components_shape(value: object) -> None:
    """Validate root components do not contain contract-bearing unsupported sections."""
    components = required_mapping(value, "components")
    unsupported_keys = set(components) - _OPENAPI_COMPONENT_KEYS
    if unsupported_keys:
        raise ManifestError(
            f"OpenAPI components has unsupported keys: {sorted(unsupported_keys)!r}"
        )
    required_mapping(components.get("schemas"), "components.schemas")
    responses = components.get("responses")
    if responses is not None and not isinstance(responses, Mapping):
        raise ManifestError("components.responses must be a mapping")


def validate_openapi_root_extension_shape(extension: Mapping[str, Any]) -> None:
    """Validate root x-usecaseapi profile metadata cannot drift silently."""
    unsupported_keys = set(extension) - _OPENAPI_ROOT_EXTENSION_KEYS
    if unsupported_keys:
        raise ManifestError(f"x-usecaseapi has unsupported keys: {sorted(unsupported_keys)!r}")
    if extension.get("defaults") != {"runtime": "python", "protocol": PROTOCOL_KIND}:
        raise ManifestError("x-usecaseapi.defaults must match the UseCaseAPI profile")
    validate_openapi_root_protocols(extension.get("protocols"))
    validate_openapi_root_runtimes(extension.get("runtimes"))
    components_value = extension.get("components")
    if components_value is None:
        return
    components = required_mapping(components_value, "x-usecaseapi.components")
    unsupported_component_keys = set(components) - _OPENAPI_ROOT_EXTENSION_COMPONENT_KEYS
    if unsupported_component_keys:
        raise ManifestError(
            f"x-usecaseapi.components has unsupported keys: {sorted(unsupported_component_keys)!r}"
        )
    required_mapping(components.get("errors"), "x-usecaseapi.components.errors")


def validate_openapi_root_protocols(value: object) -> None:
    """Validate root protocol metadata is the generated same-process profile."""
    expected = {
        PROTOCOL_KIND: {
            "type": "inprocess",
            "interaction": "requestReply",
            "action": "call",
            "async": True,
            "serialization": "none",
            "description": "Same-process async request/reply usecase call.",
        }
    }
    if value != expected:
        raise ManifestError("x-usecaseapi.protocols must match the UseCaseAPI profile")


def validate_openapi_root_runtimes(value: object) -> None:
    """Validate root runtime metadata shape."""
    runtimes = required_mapping(value, "x-usecaseapi.runtimes")
    if set(runtimes) != {"python"}:
        raise ManifestError("x-usecaseapi.runtimes must contain only python")
    runtime = required_mapping(runtimes.get("python"), "x-usecaseapi.runtimes.python")
    unsupported_keys = set(runtime) - _OPENAPI_RUNTIME_KEYS
    if unsupported_keys:
        raise ManifestError(
            f"x-usecaseapi.runtimes.python has unsupported keys: {sorted(unsupported_keys)!r}"
        )
    if runtime.get("language") != "python":
        raise ManifestError("x-usecaseapi.runtimes.python.language must be 'python'")
    if runtime.get("version") != ">=3.12,<3.15":
        raise ManifestError("x-usecaseapi.runtimes.python.version must be '>=3.12,<3.15'")
    roots = required_mapping(runtime.get("roots"), "x-usecaseapi.runtimes.python.roots")
    if set(roots) != _OPENAPI_RUNTIME_ROOT_KEYS:
        raise ManifestError("x-usecaseapi.runtimes.python.roots must define generated roots")
    for key in sorted(_OPENAPI_RUNTIME_ROOT_KEYS):
        value = roots.get(key)
        if not isinstance(value, str) or not value:
            raise ManifestError(f"x-usecaseapi.runtimes.python.roots.{key} must be a string")
    package = runtime.get("package")
    if package is not None and (not isinstance(package, str) or not package):
        raise ManifestError("x-usecaseapi.runtimes.python.package must be a string")


def validate_semantic_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate normalized UseCaseAPI semantic metadata."""
    usecases = manifest.get("usecases")
    if not isinstance(usecases, list) or not usecases:
        raise ManifestError("manifest.usecases must be a non-empty list")

    seen_keys: set[str] = set()
    for index, item in enumerate(usecases):
        if not isinstance(item, Mapping):
            raise ManifestError(f"usecases[{index}] must be a mapping")
        validate_usecase_manifest(item, seen_keys=seen_keys, index=index)
