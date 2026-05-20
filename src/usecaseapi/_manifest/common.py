"""Shared Manifest types, constants, and low-level helpers."""
# ruff: noqa: E402
# mypy: ignore-errors

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

LEGACY_MANIFEST_KIND = "usecaseapi.manifest/v1"
MANIFEST_PROFILE_KIND = "usecaseapi.openapi.profile/3.1.0"
MANIFEST_KIND = MANIFEST_PROFILE_KIND
MANIFEST_MEDIA_TYPE = "application/vnd.usecaseapi.openapi.profile.v2+yaml"
MANIFEST_EXTENSION = ".yaml"
OPENAPI_VERSION = "3.1.0"
USECASEAPI_PROFILE = "usecaseapi.openapi"
USECASEAPI_VERSION = "3.1.0"
PROTOCOL_KIND = "usecaseapi.inprocess.async_call.v1"
LEGACY_PROTOCOL_KIND = "usecaseapi.inprocess.async_call/v1"

_SCALAR_TYPE_NAMES = {
    "Any",
    "None",
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "UUID",
    "date",
    "datetime",
    "Decimal",
}
_GENERIC_TYPE_NAMES = {
    "list",
    "dict",
    "set",
    "tuple",
    "Literal",
}
_BUILTIN_TYPE_NAMES = _SCALAR_TYPE_NAMES | _GENERIC_TYPE_NAMES
_SCHEMA_METADATA_KEYS = {
    "default",
    "deprecated",
    "description",
    "examples",
    "readOnly",
    "title",
    "writeOnly",
}
_EMPTY_SCHEMA_KEYS = {"additionalProperties", "items"}
_OPENAPI_OBJECT_MODEL_SCHEMA_KEYS = {
    "additionalProperties",
    "description",
    "properties",
    "required",
    "title",
    "type",
    "x-usecaseapi",
}
_OPENAPI_PATH_ITEM_KEYS = {"post"}
_OPENAPI_OPERATION_KEYS = {
    "deprecated",
    "description",
    "operationId",
    "requestBody",
    "responses",
    "summary",
    "tags",
    "x-usecaseapi",
}
_OPENAPI_REQUEST_BODY_KEYS = {"content", "required"}
_OPENAPI_RESPONSE_KEYS = {"content", "description"}
_OPENAPI_JSON_CONTENT_KEYS = {"application/json"}
_OPENAPI_MEDIA_TYPE_KEYS = {"schema"}
_OPENAPI_OPERATION_EXTENSION_KEYS = {
    "action",
    "bindings",
    "context",
    "errors",
    "input",
    "key",
    "kind",
    "lifecycle",
    "name",
    "output",
    "protocol",
    "semantics",
    "uses",
    "version",
}
_OPENAPI_OPERATION_CONTEXT_KEYS = {"required", "schema", "source"}
_OPENAPI_OPERATION_SEMANTICS = {
    "cacheable": False,
    "idempotent": False,
    "kind": "command",
    "sideEffects": True,
}
_OPENAPI_LIFECYCLE_KEYS = {"deprecated", "stability", "supersededBy"}
_OPENAPI_ROOT_KEYS = {
    "components",
    "info",
    "jsonSchemaDialect",
    "openapi",
    "paths",
    "security",
    "servers",
    "tags",
    "x-usecaseapi",
}
_OPENAPI_COMPONENT_KEYS = {"responses", "schemas"}
_OPENAPI_ROOT_EXTENSION_KEYS = {
    "components",
    "defaults",
    "manifestKind",
    "profile",
    "protocols",
    "runtimes",
    "version",
}
_OPENAPI_ROOT_EXTENSION_COMPONENT_KEYS = {"errors"}
_OPENAPI_RUNTIME_KEYS = {"language", "package", "roots", "version"}
_OPENAPI_RUNTIME_ROOT_KEYS = {"contracts", "implementations", "tests"}
_OPENAPI_JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_JSON_SCHEMA_STRING_FORMATS = {"date", "date-time", "decimal", "uuid"}
_JSON_SCHEMA_PRIMITIVE_TYPES = {"boolean", "integer", "null", "number"}


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


@dataclass(frozen=True, slots=True)
class ManifestGuardReport:
    """Immutable-version guard result for two UseCaseAPI manifests."""

    removed: tuple[str, ...]
    changed: tuple[str, ...]
    added: tuple[str, ...]

    @property
    def failed(self) -> bool:
        """Whether immutable contract versions were removed or changed."""
        return bool(self.removed or self.changed)

    def to_dict(self) -> dict[str, list[str] | bool]:
        """Return a JSON-friendly representation."""
        return {
            "failed": self.failed,
            "removed": list(self.removed),
            "changed": list(self.changed),
            "added": list(self.added),
        }


@dataclass(frozen=True, slots=True)
class ContractCheckReport:
    """Result of validating one committed UseCaseAPI manifest."""

    manifest: str
    target: str
    manifest_valid: bool
    synchronized: bool
    guard: ManifestGuardReport | None
    errors: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        """Whether the contract check should fail CI."""
        return bool(
            self.errors
            or not self.manifest_valid
            or not self.synchronized
            or (self.guard is not None and self.guard.failed)
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly report."""
        return {
            "status": "failed" if self.failed else "passed",
            "manifest": self.manifest,
            "target": self.target,
            "validation": {
                "manifest": "passed" if self.manifest_valid else "failed",
                "sync": "passed" if self.synchronized else "failed",
            },
            "guard": self.guard.to_dict() if self.guard is not None else None,
            "errors": list(self.errors),
        }


from .accessors import *  # noqa: F403
from .helpers import *  # noqa: F403
from .rendering import *  # noqa: F403
from .semantic import *  # noqa: F403
from .semantic_validation import *  # noqa: F403

__all__ = [name for name in globals() if not name.startswith("__")]
