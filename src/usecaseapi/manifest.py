"""YAML Manifest catalog support for UseCaseAPI."""

from __future__ import annotations

import ast
import inspect
import keyword
import sys
import types

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, Union, cast, get_args, get_origin, get_type_hints

import yaml

from pydantic.fields import FieldInfo

from .api import UseCaseAPI
from .contracts import UseCaseRef
from .errors import UseCaseError
from .model import Model

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


def openapi_manifest_from_semantic(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Convert UseCaseAPI semantic metadata into the v2 OpenAPI profile."""
    usecases = usecase_items_from_semantic(manifest)
    components = openapi_components(usecases)
    project = project_name_from_semantic(manifest) or "usecaseapi-project"
    paths: dict[str, Any] = {}
    operation_ids: set[str] = set()
    tags = sorted({tag for usecase in usecases for tag in string_list(usecase.get("tags"))})
    for usecase in usecases:
        path = usecase_operation_path(usecase)
        if path in paths:
            raise ManifestError(f"duplicate OpenAPI path {path!r}")
        operation = openapi_operation(usecase)
        operation_id_value = required_string(operation, "operationId")
        if operation_id_value in operation_ids:
            raise ManifestError(f"duplicate OpenAPI operationId {operation_id_value!r}")
        operation_ids.add(operation_id_value)
        paths[path] = {"post": operation}

    return without_none(
        {
            "openapi": OPENAPI_VERSION,
            "info": {
                "title": project,
                "version": "1.0.0",
                "description": "UseCaseAPI manifest for same-process application usecases.",
                "license": {"name": "MIT", "identifier": "MIT"},
            },
            "jsonSchemaDialect": _OPENAPI_JSON_SCHEMA_DIALECT,
            "servers": [
                {
                    "url": "http://localhost",
                    "description": (
                        "Optional UseCaseAPI HTTP adapter base URL. Native UseCaseAPI calls "
                        "are same-process and do not require this transport."
                    ),
                }
            ],
            "security": [],
            "tags": [{"name": tag} for tag in tags],
            "paths": paths,
            "components": components,
            "x-usecaseapi": openapi_root_extension(manifest, usecases),
        }
    )


def openapi_root_extension(
    manifest: Mapping[str, Any],
    usecases: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the root UseCaseAPI profile extension."""
    layout = manifest.get("layout")
    layout_mapping = layout if isinstance(layout, Mapping) else {}
    package = layout_mapping.get("package")
    roots: dict[str, str] = {
        "contracts": string_or_default(layout_mapping.get("contracts_root"), "app/contracts"),
        "implementations": string_or_default(
            layout_mapping.get("implementations_root"),
            "app/usecases",
        ),
        "tests": string_or_default(layout_mapping.get("tests_root"), "tests"),
    }
    runtime: dict[str, Any] = {
        "language": "python",
        "version": ">=3.12,<3.15",
        "roots": roots,
    }
    if isinstance(package, str) and package:
        runtime["package"] = package

    return {
        "version": USECASEAPI_VERSION,
        "profile": USECASEAPI_PROFILE,
        "manifestKind": MANIFEST_PROFILE_KIND,
        "defaults": {
            "runtime": "python",
            "protocol": PROTOCOL_KIND,
        },
        "runtimes": {"python": runtime},
        "protocols": {
            PROTOCOL_KIND: {
                "type": "inprocess",
                "interaction": "requestReply",
                "action": "call",
                "async": True,
                "serialization": "none",
                "description": "Same-process async request/reply usecase call.",
            }
        },
        "components": {
            "errors": openapi_error_components(usecases),
        },
    }


def openapi_operation(usecase: Mapping[str, Any]) -> dict[str, Any]:
    """Build one OpenAPI operation for a UseCaseAPI call."""
    key = usecase_key(usecase)
    tags = [*string_list(usecase.get("tags")), *string_list(usecase.get("binding_tags"))]
    input_schema = component_ref(component_name(usecase, required_string(usecase, "input")))
    output_schema = component_ref(component_name(usecase, required_string(usecase, "output")))
    description = usecase.get("description")
    raises = string_list(usecase.get("raises"))
    known_errors = string_list(usecase.get("known_errors"))
    responses: dict[str, Any] = {
        "200": {
            "description": response_description(usecase),
            "content": {"application/json": {"schema": output_schema}},
        },
    }
    if raises or known_errors:
        responses["default"] = {
            "$ref": f"#/components/responses/{response_component_name(usecase)}"
        }

    return without_none(
        {
            "operationId": operation_id(usecase),
            "tags": tags,
            "summary": description,
            "description": description,
            "deprecated": bool(usecase.get("deprecated", False)),
            "requestBody": {
                "required": True,
                "content": {"application/json": {"schema": input_schema}},
            },
            "responses": responses,
            "x-usecaseapi": {
                "kind": "usecase",
                "key": key,
                "name": required_string(usecase, "name"),
                "version": required_int(usecase, "version"),
                "action": "call",
                "lifecycle": {
                    "stability": "stable" if usecase.get("stable", True) else "experimental",
                    "deprecated": bool(usecase.get("deprecated", False)),
                    "supersededBy": usecase.get("superseded_by"),
                },
                "protocol": PROTOCOL_KIND,
                "semantics": {
                    "kind": "command",
                    "sideEffects": True,
                    "idempotent": False,
                    "cacheable": False,
                },
                "context": {"source": "runtime", "required": False, "schema": None},
                "input": {
                    "pythonName": required_string(usecase, "input"),
                    "schema": input_schema["$ref"],
                },
                "output": {
                    "pythonName": required_string(usecase, "output"),
                    "schema": output_schema["$ref"],
                },
                "errors": {"raises": raises, "known": known_errors},
                "uses": openapi_uses(usecase),
                "bindings": {"python": openapi_python_binding(usecase)},
            },
        }
    )


def openapi_uses(usecase: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Build OpenAPI dependency metadata and reject ambiguous dependency names."""
    uses: dict[str, dict[str, Any]] = {}
    for use_key in string_list(usecase.get("uses")):
        name = dependency_name(use_key)
        if name in uses:
            raise ManifestError(f"duplicate dependency name {name!r} in {usecase_key(usecase)!r}")
        uses[name] = {"key": use_key, "required": True}
    return uses


def openapi_python_binding(usecase: Mapping[str, Any]) -> dict[str, Any]:
    """Build Python binding metadata for one operation."""
    source = required_mapping(usecase.get("source"), "usecase.source")
    contract: dict[str, Any] = {
        "module": required_string(source, "contract_module"),
        "protocolClass": required_string(source, "protocol_class"),
        "ref": required_string(source, "ref"),
    }
    contract_file = source.get("contract_file")
    if isinstance(contract_file, str) and contract_file:
        contract["file"] = contract_file
    implementation: dict[str, Any] = {}
    implementation_class = source.get("implementation_class")
    if isinstance(implementation_class, str) and implementation_class:
        implementation["class"] = implementation_class
    implementation_file = source.get("implementation_file")
    if isinstance(implementation_file, str) and implementation_file:
        implementation["file"] = implementation_file
    binding: dict[str, Any] = {
        "signature": (
            f"async __call__(input: {required_string(usecase, 'input')}) -> "
            f"{required_string(usecase, 'output')}"
        ),
        "contract": contract,
    }
    if implementation:
        binding["implementation"] = implementation
    return binding


def openapi_components(usecases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build OpenAPI reusable components."""
    schemas: dict[str, Any] = {}
    responses: dict[str, Any] = {}
    for usecase in usecases:
        for model in manifest_models(usecase):
            name = component_name(usecase, required_string(model, "name"))
            if name in schemas:
                raise ManifestError(f"duplicate OpenAPI schema component {name!r}")
            schemas[name] = model_schema(usecase, model)
        for error in manifest_errors(usecase):
            payload_name = error_payload_component_name(usecase, error)
            envelope_name = error_envelope_component_name(usecase, error)
            if payload_name in schemas:
                raise ManifestError(f"duplicate OpenAPI schema component {payload_name!r}")
            if envelope_name in schemas:
                raise ManifestError(f"duplicate OpenAPI schema component {envelope_name!r}")
            schemas[payload_name] = error_payload_schema(usecase, error)
            schemas[envelope_name] = error_envelope_schema(error, payload_name)
        if string_list(usecase.get("raises")) or string_list(usecase.get("known_errors")):
            name = response_component_name(usecase)
            if name in responses:
                raise ManifestError(f"duplicate OpenAPI response component {name!r}")
            responses[name] = domain_error_response(usecase)
    result: dict[str, Any] = {"schemas": schemas}
    if responses:
        result["responses"] = responses
    return result


def model_schema(usecase: Mapping[str, Any], model: Mapping[str, Any]) -> dict[str, Any]:
    """Convert Manifest model metadata to an OpenAPI schema component."""
    model_name = required_string(model, "name")
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in manifest_fields(model):
        field_name = required_string(field, "name")
        properties[field_name] = field_schema(usecase, field)
        if field.get("required", True) is True:
            required.append(field_name)
    result = without_none(
        {
            "title": model_name,
            "description": model.get("description"),
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": properties,
            "x-usecaseapi": {
                "kind": schema_kind(usecase, model_name),
                "canonicalName": (
                    f"{required_string(usecase, 'name')}.v{required_int(usecase, 'version')}."
                    f"{model_name}"
                ),
                "bindings": {"python": {"class": model_name}},
            },
        }
    )
    result["properties"] = properties
    return result


def error_payload_schema(usecase: Mapping[str, Any], error: Mapping[str, Any]) -> dict[str, Any]:
    """Build an error payload schema."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in manifest_fields(error):
        field_name = required_string(field, "name")
        properties[field_name] = field_schema(usecase, field)
        if field.get("required", True) is True:
            required.append(field_name)
    result = without_none(
        {
            "title": required_string(error, "name") + "Payload",
            "description": error.get("description"),
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": properties,
        }
    )
    result["properties"] = properties
    return result


def field_schema(usecase: Mapping[str, Any], field: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a Manifest field to a JSON Schema fragment."""
    schema = type_expr_to_schema(required_string(field, "type"), usecase=usecase)
    description = field.get("description")
    if isinstance(description, str) and description:
        schema["description"] = description
    return schema


def type_expr_to_schema(expr: str, *, usecase: Mapping[str, Any]) -> dict[str, Any]:
    """Convert the supported Manifest annotation subset to JSON Schema."""
    validate_type_expr(expr)
    primitive = primitive_type_expr_to_schema(expr)
    if primitive is not None:
        return primitive
    if expr in {"Any", "None"}:
        return {} if expr == "Any" else {"type": "null"}
    if expr in {"UUID", "date", "datetime", "Decimal"}:
        formats = {"UUID": "uuid", "date": "date", "datetime": "date-time", "Decimal": "decimal"}
        return {"type": "string", "format": formats[expr]}
    parsed = ast.parse(expr, mode="eval").body
    if isinstance(parsed, ast.Name):
        if usecase:
            return component_ref(component_name(usecase, parsed.id))
        return {}
    return type_ast_to_schema(parsed, usecase=usecase)


def primitive_type_expr_to_schema(expr: str) -> dict[str, Any] | None:
    """Convert primitive Python type expressions to JSON Schema."""
    schemas = {
        "str": {"type": "string"},
        "int": {"type": "integer"},
        "float": {"type": "number"},
        "bool": {"type": "boolean"},
        "bytes": {"type": "string", "contentEncoding": "base64"},
    }
    return schemas.get(expr)


def type_ast_to_schema(node: ast.AST, *, usecase: Mapping[str, Any]) -> dict[str, Any]:
    """Convert parsed annotation syntax to JSON Schema."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return {
            "anyOf": [
                type_ast_to_schema(node.left, usecase=usecase),
                type_ast_to_schema(node.right, usecase=usecase),
            ]
        }
    if isinstance(node, ast.Constant) and node.value is None:
        return {"type": "null"}
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        return subscript_ast_to_schema(node, usecase=usecase)
    if isinstance(node, ast.Name):
        return type_expr_to_schema(node.id, usecase=usecase)
    if isinstance(node, ast.Constant):
        return {"const": node.value}
    return {}


def subscript_ast_to_schema(node: ast.Subscript, *, usecase: Mapping[str, Any]) -> dict[str, Any]:
    """Convert supported subscript annotation syntax to JSON Schema."""
    if not isinstance(node.value, ast.Name):
        return {}
    name = node.value.id
    args = subscript_args(node.slice)
    if name == "Literal":
        return {"enum": literal_values(node.slice)}
    if name == "list":
        return {"type": "array", "items": ast_arg_schema(args, 0, usecase=usecase)}
    if name == "set":
        return {
            "type": "array",
            "uniqueItems": True,
            "items": ast_arg_schema(args, 0, usecase=usecase),
        }
    if name == "dict":
        return {
            "type": "object",
            "additionalProperties": ast_arg_schema(args, 1, usecase=usecase),
        }
    if name == "tuple":
        return {
            "type": "array",
            "prefixItems": [type_ast_to_schema(arg, usecase=usecase) for arg in args],
            "minItems": len(args),
            "maxItems": len(args),
        }
    return {}


def ast_arg_schema(
    args: Sequence[ast.AST], index: int, *, usecase: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the JSON Schema for one annotation argument."""
    if len(args) <= index:
        return {}
    return type_ast_to_schema(args[index], usecase=usecase)


def literal_values(node: ast.AST) -> list[Any]:
    """Return values from a Literal[...] AST node."""
    return [item.value for item in subscript_args(node) if isinstance(item, ast.Constant)]


def subscript_args(node: ast.AST) -> list[ast.AST]:
    """Return subscript arguments as a list."""
    if isinstance(node, ast.Tuple):
        return list(node.elts)
    return [node]


def error_envelope_schema(error: Mapping[str, Any], payload_name: str) -> dict[str, Any]:
    """Build a domain error envelope schema."""
    error_name = required_string(error, "name")
    code = required_string(error, "code")
    return {
        "title": error_name + "Envelope",
        "description": error.get("description", f"Domain error envelope for {error_name}."),
        "type": "object",
        "additionalProperties": False,
        "required": ["code", "error", "message", "payload"],
        "properties": {
            "code": {"type": "string", "enum": [code]},
            "error": {"type": "string", "enum": [error_name]},
            "message": {"type": "string"},
            "payload": component_ref(payload_name),
        },
        "x-usecaseapi": {"kind": "errorEnvelope", "error": error_name},
    }


def domain_error_response(usecase: Mapping[str, Any]) -> dict[str, Any]:
    """Build an OpenAPI response for declared domain errors."""
    error_names = [*string_list(usecase.get("raises")), *string_list(usecase.get("known_errors"))]
    errors_by_name = {required_string(error, "name"): error for error in manifest_errors(usecase)}
    refs = [
        component_ref(error_envelope_component_name(usecase, errors_by_name[name]))
        for name in error_names
        if name in errors_by_name
    ]
    return {
        "description": f"Domain error raised by {required_string(usecase, 'name')}.",
        "content": {"application/json": {"schema": {"oneOf": refs}}},
    }


def openapi_error_components(usecases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build x-usecaseapi error hierarchy metadata."""
    errors: dict[str, Any] = {}
    for usecase in usecases:
        for error in manifest_errors(usecase):
            error_name = required_string(error, "name")
            component_key = error_component_name(usecase, error)
            if component_key in errors:
                raise ManifestError(f"duplicate OpenAPI error component {component_key!r}")
            errors[component_key] = {
                "name": error_name,
                "code": required_string(error, "code"),
                "abstract": error_name in string_list(usecase.get("raises")),
                "base": string_or_default(error.get("base"), "UseCaseError"),
                "payloadSchema": component_ref_path(error_payload_component_name(usecase, error)),
                "envelopeSchema": component_ref_path(error_envelope_component_name(usecase, error)),
                "bindings": {"python": {"class": error_name}},
                "description": error.get("description"),
            }
            errors[component_key] = without_none(errors[component_key])
    return errors


def usecase_operation_path(usecase: Mapping[str, Any]) -> str:
    """Return the v2 canonical OpenAPI path for a usecase call."""
    name = required_string(usecase, "name")
    version = required_int(usecase, "version")
    return f"/_usecases/{name}/v{version}/call"


def component_name(usecase: Mapping[str, Any], class_name_value: str) -> str:
    """Return an OpenAPI component key friendly to code generators."""
    prefix = "".join(
        pascal_identifier(part) for part in required_string(usecase, "name").split(".")
    )
    return f"{prefix}V{required_int(usecase, 'version')}{class_name_value}"


def error_component_name(usecase: Mapping[str, Any], error: Mapping[str, Any]) -> str:
    """Return the x-usecaseapi error component key."""
    return component_name(usecase, required_string(error, "name"))


def error_payload_component_name(usecase: Mapping[str, Any], error: Mapping[str, Any]) -> str:
    """Return the payload schema component key for an error."""
    return component_name(usecase, required_string(error, "name") + "Payload")


def error_envelope_component_name(usecase: Mapping[str, Any], error: Mapping[str, Any]) -> str:
    """Return the envelope schema component key for an error."""
    return component_name(usecase, required_string(error, "name") + "Envelope")


def response_component_name(usecase: Mapping[str, Any]) -> str:
    """Return the domain error response component key for a usecase."""
    return component_name(usecase, "DomainError")


def component_ref(name: str) -> dict[str, str]:
    """Return an OpenAPI component reference."""
    return {"$ref": component_ref_path(name)}


def component_ref_path(name: str) -> str:
    """Return an OpenAPI schema component reference path."""
    return f"#/components/schemas/{name}"


def operation_id(usecase: Mapping[str, Any]) -> str:
    """Return a stable OpenAPI operationId."""
    return (
        required_string(usecase, "name").replace(".", "_")
        + f"_v{required_int(usecase, 'version')}_call"
    )


def dependency_name(key: str) -> str:
    """Return a readable dependency map key."""
    name, _, _version = key.partition("@v")
    return name.split(".")[-1]


def response_description(usecase: Mapping[str, Any]) -> str:
    """Return the success response description."""
    output = required_string(usecase, "output")
    return f"{output} result."


def schema_kind(usecase: Mapping[str, Any], model_name: str) -> str:
    """Return UseCaseAPI schema role metadata."""
    if model_name == required_string(usecase, "input"):
        return "input"
    if model_name == required_string(usecase, "output"):
        return "output"
    return "model"


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


def semantic_from_openapi_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a v2 OpenAPI profile Manifest to UseCaseAPI semantic metadata."""
    paths = required_mapping(manifest.get("paths"), "paths")
    root_extension = required_mapping(manifest.get("x-usecaseapi"), "x-usecaseapi")
    info = required_mapping(manifest.get("info"), "info")
    usecases: list[dict[str, Any]] = []
    for path, path_item in paths.items():
        if not isinstance(path, str):
            raise ManifestError("OpenAPI path keys must be strings")
        validate_openapi_path_item(path, path_item)
        path_item_mapping = required_mapping(path_item, f"paths.{path}")
        operation = required_mapping(path_item_mapping.get("post"), f"paths.{path}.post")
        extension = operation.get("x-usecaseapi")
        if not isinstance(extension, Mapping) or extension.get("kind") != "usecase":
            raise ManifestError(f"paths.{path}.post must declare a usecase operation")
        usecases.append(openapi_operation_to_usecase(path, operation, extension, manifest))

    return {
        "kind": LEGACY_MANIFEST_KIND,
        "metadata": {"name": required_string(info, "title")},
        "layout": semantic_layout(root_extension),
        "usecases": sorted(usecases, key=lambda item: required_string(item, "key")),
    }


def semantic_layout(root_extension: Mapping[str, Any]) -> dict[str, Any]:
    """Read v2 runtime roots into semantic layout metadata."""
    runtimes = root_extension.get("runtimes")
    python_runtime = {}
    if isinstance(runtimes, Mapping):
        runtime = runtimes.get("python")
        if isinstance(runtime, Mapping):
            python_runtime = dict(runtime)
    roots = python_runtime.get("roots")
    root_mapping = roots if isinstance(roots, Mapping) else {}
    layout = {
        "contracts_root": string_or_default(root_mapping.get("contracts"), "app/contracts"),
        "implementations_root": string_or_default(
            root_mapping.get("implementations"),
            "app/usecases",
        ),
        "tests_root": string_or_default(root_mapping.get("tests"), "tests"),
    }
    package = python_runtime.get("package")
    if isinstance(package, str) and package:
        layout["package"] = package
    return layout


def openapi_operation_to_usecase(
    path: str,
    operation: Mapping[str, Any],
    extension: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert one v2 operation into semantic usecase metadata."""
    name = required_string(extension, "name")
    version = required_int(extension, "version")
    key = string_or_default(extension.get("key"), f"{name}@v{version}")
    lifecycle_value = extension.get("lifecycle")
    lifecycle = lifecycle_value if isinstance(lifecycle_value, Mapping) else {}
    input_value = required_mapping(extension.get("input"), "x-usecaseapi.input")
    output_value = required_mapping(extension.get("output"), "x-usecaseapi.output")
    errors_value = extension.get("errors")
    errors = errors_value if isinstance(errors_value, Mapping) else {}
    validate_openapi_operation_extension(extension, operation=operation)
    validate_openapi_operation_shape(
        operation, has_errors=openapi_operation_declares_errors(errors)
    )
    validate_openapi_operation_identity(operation, name=name, version=version)
    validate_openapi_operation_contract_schemas(
        manifest,
        operation,
        name=name,
        version=version,
        input_value=input_value,
        output_value=output_value,
        errors_value=errors,
    )
    bindings_value = required_mapping(extension.get("bindings"), "x-usecaseapi.bindings")
    python_binding = required_mapping(bindings_value.get("python"), "x-usecaseapi.bindings.python")
    source = source_from_python_binding(python_binding)
    usecase = {
        "name": name,
        "version": version,
        "key": key,
        "description": operation.get("description") or operation.get("summary"),
        "stable": lifecycle.get("stability", "stable") == "stable",
        "deprecated": bool(operation.get("deprecated", lifecycle.get("deprecated", False))),
        "superseded_by": lifecycle.get("supersededBy"),
        "tags": string_list(operation.get("tags")),
        "protocol": {
            "kind": PROTOCOL_KIND,
            "signature": python_binding.get("signature"),
        },
        "source": source,
        "input": required_string(input_value, "pythonName"),
        "output": required_string(output_value, "pythonName"),
        "models": models_from_components(manifest, name=name, version=version),
        "errors": errors_from_components(manifest, name=name, version=version),
        "raises": string_list(errors.get("raises")),
        "known_errors": string_list(errors.get("known")),
        "uses": uses_from_extension(extension),
    }
    expected_path = f"/_usecases/{name}/v{version}/call"
    if path != expected_path:
        raise ManifestError(f"usecase path must be {expected_path!r}")
    return without_none(usecase)


def openapi_operation_declares_errors(errors: Mapping[str, Any]) -> bool:
    """Return whether an OpenAPI operation declares public error responses."""
    return bool(string_list(errors.get("raises")) or string_list(errors.get("known")))


def validate_openapi_operation_extension(
    extension: Mapping[str, Any],
    *,
    operation: Mapping[str, Any],
) -> None:
    """Validate x-usecaseapi operation metadata does not drift from the runtime profile."""
    unsupported_keys = set(extension) - _OPENAPI_OPERATION_EXTENSION_KEYS
    if unsupported_keys:
        raise ManifestError(
            f"x-usecaseapi operation has unsupported keys: {sorted(unsupported_keys)!r}"
        )
    if extension.get("kind") != "usecase":
        raise ManifestError("x-usecaseapi.kind must be 'usecase'")
    if extension.get("action") != "call":
        raise ManifestError("x-usecaseapi.action must be 'call'")
    if extension.get("protocol") != PROTOCOL_KIND:
        raise ManifestError(f"x-usecaseapi.protocol must be {PROTOCOL_KIND!r}")
    validate_openapi_operation_context(extension)
    validate_openapi_operation_semantics(extension)
    validate_openapi_operation_lifecycle(extension, operation=operation)
    validate_openapi_operation_uses(extension)


def validate_openapi_operation_context(extension: Mapping[str, Any]) -> None:
    """Validate UseCaseAPI runtime context metadata is not changed into request contract."""
    context = required_mapping(extension.get("context"), "x-usecaseapi.context")
    unsupported_keys = set(context) - _OPENAPI_OPERATION_CONTEXT_KEYS
    if unsupported_keys:
        raise ManifestError(
            f"x-usecaseapi.context has unsupported keys: {sorted(unsupported_keys)!r}"
        )
    if context.get("source") != "runtime":
        raise ManifestError("x-usecaseapi.context.source must be 'runtime'")
    if context.get("required") is not False:
        raise ManifestError("x-usecaseapi.context.required must be false")
    if "schema" in context and context.get("schema") is not None:
        raise ManifestError("x-usecaseapi.context.schema must be null when present")


def validate_openapi_operation_semantics(extension: Mapping[str, Any]) -> None:
    """Validate operation semantics metadata remains the generated same-process profile."""
    semantics = required_mapping(extension.get("semantics"), "x-usecaseapi.semantics")
    if dict(semantics) != _OPENAPI_OPERATION_SEMANTICS:
        raise ManifestError("x-usecaseapi.semantics must match the generated call profile")


def validate_openapi_operation_lifecycle(
    extension: Mapping[str, Any],
    *,
    operation: Mapping[str, Any],
) -> None:
    """Validate lifecycle metadata agrees with the public operation flags."""
    lifecycle = required_mapping(extension.get("lifecycle"), "x-usecaseapi.lifecycle")
    unsupported_keys = set(lifecycle) - _OPENAPI_LIFECYCLE_KEYS
    if unsupported_keys:
        raise ManifestError(
            f"x-usecaseapi.lifecycle has unsupported keys: {sorted(unsupported_keys)!r}"
        )
    stability = lifecycle.get("stability")
    if stability not in {"stable", "experimental"}:
        raise ManifestError("x-usecaseapi.lifecycle.stability must be stable or experimental")
    deprecated = lifecycle.get("deprecated")
    if not isinstance(deprecated, bool):
        raise ManifestError("x-usecaseapi.lifecycle.deprecated must be a boolean")
    if deprecated is not bool(operation.get("deprecated", False)):
        raise ManifestError("x-usecaseapi.lifecycle.deprecated must match operation.deprecated")
    superseded_by = lifecycle.get("supersededBy")
    if superseded_by is not None and not isinstance(superseded_by, str):
        raise ManifestError("x-usecaseapi.lifecycle.supersededBy must be a string when present")


def validate_openapi_operation_uses(extension: Mapping[str, Any]) -> None:
    """Validate dependency extension entries remain required same-process dependencies."""
    uses_value = extension.get("uses", {})
    if not isinstance(uses_value, Mapping):
        raise ManifestError("x-usecaseapi.uses must be a mapping")
    for name, metadata in uses_value.items():
        if not isinstance(name, str) or not isinstance(metadata, Mapping):
            raise ManifestError("x-usecaseapi.uses entries must be named mappings")
        if set(metadata) != {"key", "required"}:
            raise ManifestError("x-usecaseapi.uses entries must contain only key and required")
        key = required_string(metadata, "key")
        if name != dependency_name(key):
            raise ManifestError(f"x-usecaseapi.uses entry {name!r} must match {key!r}")
        if metadata.get("required") is not True:
            raise ManifestError("x-usecaseapi.uses entries must be required")


def validate_openapi_path_item(path: str, path_item: object) -> None:
    """Validate a UseCaseAPI OpenAPI path item does not expose extra endpoints."""
    if not isinstance(path_item, Mapping):
        raise ManifestError(f"path item {path!r} must be a mapping")
    if set(path_item) != _OPENAPI_PATH_ITEM_KEYS:
        raise ManifestError(f"path item {path!r} must contain only post")


def validate_openapi_operation_shape(operation: Mapping[str, Any], *, has_errors: bool) -> None:
    """Validate operation-level OpenAPI fields preserve the UseCaseAPI profile contract."""
    unsupported_keys = set(operation) - _OPENAPI_OPERATION_KEYS
    if unsupported_keys:
        raise ManifestError(f"operation has unsupported keys: {sorted(unsupported_keys)!r}")
    request_body = required_mapping(operation.get("requestBody"), "operation.requestBody")
    if set(request_body) != _OPENAPI_REQUEST_BODY_KEYS:
        raise ManifestError("operation.requestBody must contain only required and content")
    if request_body.get("required") is not True:
        raise ManifestError("operation.requestBody.required must be true")
    request_content = required_mapping(
        request_body.get("content"),
        "operation.requestBody.content",
    )
    validate_openapi_json_content(request_content, "operation.requestBody.content")

    responses = required_mapping(operation.get("responses"), "operation.responses")
    expected_response_keys = {"200", "default"} if has_errors else {"200"}
    if set(responses) != expected_response_keys:
        raise ManifestError(
            f"operation.responses must contain exactly {sorted(expected_response_keys)!r}"
        )
    success = required_mapping(responses.get("200"), "operation.responses.200")
    if set(success) != _OPENAPI_RESPONSE_KEYS:
        raise ManifestError("operation.responses.200 must contain only description and content")
    success_content = required_mapping(success.get("content"), "operation.responses.200.content")
    validate_openapi_json_content(success_content, "operation.responses.200.content")
    if has_errors:
        default_response = required_mapping(
            responses.get("default"),
            "operation.responses.default",
        )
        if set(default_response) != {"$ref"}:
            raise ManifestError("operation.responses.default must contain only $ref")


def validate_openapi_operation_identity(
    operation: Mapping[str, Any],
    *,
    name: str,
    version: int,
) -> None:
    """Validate code-generation identity fields match the declared usecase identity."""
    expected_operation_id = operation_id({"name": name, "version": version})
    actual_operation_id = required_string(operation, "operationId")
    if actual_operation_id != expected_operation_id:
        raise ManifestError(
            f"operationId must be {expected_operation_id!r}, got {actual_operation_id!r}"
        )


def validate_openapi_json_content(content: Mapping[str, Any], location: str) -> None:
    """Validate an OpenAPI content map contains only the JSON schema media type."""
    if set(content) != _OPENAPI_JSON_CONTENT_KEYS:
        raise ManifestError(f"{location} must contain only application/json")
    media_type = required_mapping(content.get("application/json"), f"{location}.application/json")
    if set(media_type) != _OPENAPI_MEDIA_TYPE_KEYS:
        raise ManifestError(f"{location}.application/json must contain only schema")


def validate_openapi_operation_contract_schemas(
    manifest: Mapping[str, Any],
    operation: Mapping[str, Any],
    *,
    name: str,
    version: int,
    input_value: Mapping[str, Any],
    output_value: Mapping[str, Any],
    errors_value: Mapping[str, Any],
) -> None:
    """Validate operation schemas match the x-usecaseapi contract metadata."""
    identity = {"name": name, "version": version}
    expected_input = component_ref_path(
        component_name(identity, required_string(input_value, "pythonName"))
    )
    expected_output = component_ref_path(
        component_name(identity, required_string(output_value, "pythonName"))
    )
    actual_input_metadata = required_string(input_value, "schema")
    if actual_input_metadata != expected_input:
        raise ManifestError(
            f"x-usecaseapi.input.schema must be {expected_input!r}, got {actual_input_metadata!r}"
        )
    actual_output_metadata = required_string(output_value, "schema")
    if actual_output_metadata != expected_output:
        raise ManifestError(
            f"x-usecaseapi.output.schema must be {expected_output!r}, "
            f"got {actual_output_metadata!r}"
        )
    actual_input_operation = openapi_request_body_schema_ref(operation)
    if actual_input_operation != expected_input:
        raise ManifestError(
            f"requestBody schema must be {expected_input!r}, got {actual_input_operation!r}"
        )
    actual_output_operation = openapi_success_response_schema_ref(operation)
    if actual_output_operation != expected_output:
        raise ManifestError(
            f"200 response schema must be {expected_output!r}, got {actual_output_operation!r}"
        )
    validate_openapi_operation_error_response(
        manifest,
        operation,
        identity=identity,
        errors_value=errors_value,
    )


def openapi_request_body_schema_ref(operation: Mapping[str, Any]) -> str:
    """Return the JSON request body schema reference for an operation."""
    request_body = required_mapping(operation.get("requestBody"), "operation.requestBody")
    content = required_mapping(request_body.get("content"), "operation.requestBody.content")
    media_type = required_mapping(
        content.get("application/json"),
        "operation.requestBody.content.application/json",
    )
    schema = required_mapping(
        media_type.get("schema"),
        "operation.requestBody.content.application/json.schema",
    )
    return required_string(schema, "$ref")


def openapi_success_response_schema_ref(operation: Mapping[str, Any]) -> str:
    """Return the JSON 200 response schema reference for an operation."""
    responses = required_mapping(operation.get("responses"), "operation.responses")
    success = required_mapping(responses.get("200"), "operation.responses.200")
    content = required_mapping(success.get("content"), "operation.responses.200.content")
    media_type = required_mapping(
        content.get("application/json"),
        "operation.responses.200.content.application/json",
    )
    schema = required_mapping(
        media_type.get("schema"),
        "operation.responses.200.content.application/json.schema",
    )
    return required_string(schema, "$ref")


def validate_openapi_operation_error_response(
    manifest: Mapping[str, Any],
    operation: Mapping[str, Any],
    *,
    identity: Mapping[str, Any],
    errors_value: Mapping[str, Any],
) -> None:
    """Validate the default error response matches declared error metadata."""
    error_names = [
        *string_list(errors_value.get("raises")),
        *string_list(errors_value.get("known")),
    ]
    if not error_names:
        return
    expected_response = f"#/components/responses/{response_component_name(identity)}"
    actual_response = openapi_default_response_ref(operation)
    if actual_response != expected_response:
        raise ManifestError(
            f"default response must be {expected_response!r}, got {actual_response!r}"
        )
    actual_envelopes = openapi_error_response_envelope_refs(manifest, actual_response)
    expected_envelopes = openapi_error_envelope_refs(manifest, identity, error_names)
    if actual_envelopes != expected_envelopes:
        raise ManifestError(
            f"default response envelopes must be {expected_envelopes!r}, got {actual_envelopes!r}"
        )


def openapi_default_response_ref(operation: Mapping[str, Any]) -> str:
    """Return the default response component reference for an operation."""
    responses = required_mapping(operation.get("responses"), "operation.responses")
    default = required_mapping(responses.get("default"), "operation.responses.default")
    return required_string(default, "$ref")


def openapi_error_response_envelope_refs(
    manifest: Mapping[str, Any],
    response_ref: str,
) -> list[str]:
    """Return error envelope schema references from a response component."""
    prefix = "#/components/responses/"
    if not response_ref.startswith(prefix):
        raise ManifestError(f"unsupported response reference {response_ref!r}")
    components = required_mapping(manifest.get("components"), "components")
    responses = required_mapping(components.get("responses"), "components.responses")
    response = required_mapping(responses.get(response_ref.removeprefix(prefix)), response_ref)
    content = required_mapping(response.get("content"), f"{response_ref}.content")
    media_type = required_mapping(
        content.get("application/json"),
        f"{response_ref}.content.application/json",
    )
    schema = required_mapping(media_type.get("schema"), f"{response_ref}.schema")
    one_of = schema.get("oneOf")
    if not isinstance(one_of, list):
        raise ManifestError("default response schema oneOf must be a list")
    refs: list[str] = []
    for item in one_of:
        if not isinstance(item, Mapping):
            raise ManifestError("default response schema oneOf entries must be mappings")
        refs.append(required_string(item, "$ref"))
    return refs


def openapi_error_envelope_refs(
    manifest: Mapping[str, Any],
    identity: Mapping[str, Any],
    error_names: Sequence[str],
) -> list[str]:
    """Return expected error envelope refs from x-usecaseapi error metadata."""
    root_extension = required_mapping(manifest.get("x-usecaseapi"), "x-usecaseapi")
    components_value = root_extension.get("components")
    components = components_value if isinstance(components_value, Mapping) else {}
    errors_value = components.get("errors")
    errors = errors_value if isinstance(errors_value, Mapping) else {}
    refs: list[str] = []
    for error_name in error_names:
        metadata_key = component_name(identity, error_name)
        metadata = required_mapping(
            errors.get(metadata_key),
            f"x-usecaseapi.components.errors.{metadata_key}",
        )
        expected_payload = component_ref_path(component_name(identity, error_name + "Payload"))
        expected_envelope = component_ref_path(component_name(identity, error_name + "Envelope"))
        actual_payload = required_string(metadata, "payloadSchema")
        if actual_payload != expected_payload:
            raise ManifestError(
                f"error metadata payloadSchema must be {expected_payload!r}, got {actual_payload!r}"
            )
        actual_envelope = required_string(metadata, "envelopeSchema")
        if actual_envelope != expected_envelope:
            raise ManifestError(
                f"error metadata envelopeSchema must be {expected_envelope!r}, "
                f"got {actual_envelope!r}"
            )
        validate_openapi_error_envelope_schema(
            manifest,
            error_name=error_name,
            error_code=required_string(metadata, "code"),
            expected_payload=expected_payload,
            expected_envelope=expected_envelope,
        )
        refs.append(expected_envelope)
    return refs


def validate_openapi_error_envelope_schema(
    manifest: Mapping[str, Any],
    *,
    error_name: str,
    error_code: str,
    expected_payload: str,
    expected_envelope: str,
) -> None:
    """Validate an error envelope component matches its error metadata."""
    envelope = schema_by_ref(manifest, expected_envelope)
    if envelope.get("additionalProperties") is not False:
        raise ManifestError(f"error envelope {expected_envelope!r} must forbid extra fields")
    required_names = set(string_list(envelope.get("required")))
    expected_required = {"code", "error", "message", "payload"}
    if required_names != expected_required:
        raise ManifestError(
            f"error envelope {expected_envelope!r} required fields must be "
            f"{sorted(expected_required)!r}"
        )
    properties = required_mapping(envelope.get("properties"), f"{expected_envelope}.properties")
    expected_properties = {"code", "error", "message", "payload"}
    if set(properties) != expected_properties:
        raise ManifestError(
            f"error envelope {expected_envelope!r} properties must be "
            f"{sorted(expected_properties)!r}"
        )
    payload = required_mapping(
        properties.get("payload"),
        f"{expected_envelope}.properties.payload",
    )
    actual_payload = required_string(payload, "$ref")
    if actual_payload != expected_payload:
        raise ManifestError(
            f"error envelope {expected_envelope!r} payload must be {expected_payload!r}, "
            f"got {actual_payload!r}"
        )
    validate_openapi_error_envelope_enum(
        properties,
        expected_envelope=expected_envelope,
        field_name="code",
        expected_value=error_code,
    )
    validate_openapi_error_envelope_enum(
        properties,
        expected_envelope=expected_envelope,
        field_name="error",
        expected_value=error_name,
    )
    message = required_mapping(
        properties.get("message"),
        f"{expected_envelope}.properties.message",
    )
    if message.get("type") != "string":
        raise ManifestError(f"error envelope {expected_envelope!r} message must be string")


def validate_openapi_error_envelope_enum(
    properties: Mapping[str, Any],
    *,
    expected_envelope: str,
    field_name: str,
    expected_value: str,
) -> None:
    """Validate an error envelope string enum property."""
    schema = required_mapping(
        properties.get(field_name),
        f"{expected_envelope}.properties.{field_name}",
    )
    if schema.get("type") != "string":
        raise ManifestError(f"error envelope {expected_envelope!r} {field_name} must be string")
    enum = schema.get("enum")
    if enum != [expected_value]:
        raise ManifestError(
            f"error envelope {expected_envelope!r} {field_name} enum must be {[expected_value]!r}"
        )


def source_from_python_binding(binding: Mapping[str, Any]) -> dict[str, Any]:
    """Read Python source mapping from v2 binding metadata."""
    contract = required_mapping(binding.get("contract"), "python.contract")
    source = {
        "contract_module": required_string(contract, "module"),
        "protocol_class": required_string(contract, "protocolClass"),
        "ref": required_string(contract, "ref"),
    }
    contract_file = contract.get("file")
    if isinstance(contract_file, str) and contract_file:
        source["contract_file"] = contract_file
    implementation_value = binding.get("implementation")
    if isinstance(implementation_value, Mapping):
        implementation_class = implementation_value.get("class")
        implementation_file = implementation_value.get("file")
        if isinstance(implementation_class, str) and implementation_class:
            source["implementation_class"] = implementation_class
        if isinstance(implementation_file, str) and implementation_file:
            source["implementation_file"] = implementation_file
    return source


def models_from_components(
    manifest: Mapping[str, Any],
    *,
    name: str,
    version: int,
) -> list[dict[str, Any]]:
    """Read model metadata from OpenAPI component schemas."""
    schemas = component_schemas(manifest)
    identity = {"name": name, "version": version}
    models: list[dict[str, Any]] = []
    for component_key, schema_value in schemas.items():
        if not isinstance(schema_value, Mapping):
            continue
        extension = schema_value.get("x-usecaseapi")
        if not isinstance(extension, Mapping):
            continue
        if extension.get("kind") not in {"model", "input", "output"}:
            continue
        bindings = extension.get("bindings")
        python = bindings.get("python") if isinstance(bindings, Mapping) else None
        class_name_value = python.get("class") if isinstance(python, Mapping) else None
        model_name = (
            class_name_value if isinstance(class_name_value, str) else schema_value.get("title")
        )
        if not isinstance(model_name, str) or not model_name:
            raise ManifestError(f"schema {component_key!r} must declare a Python class")
        expected_canonical = f"{name}.v{version}.{model_name}"
        canonical_name = required_string(extension, "canonicalName")
        if canonical_name != expected_canonical:
            continue
        expected_component_key = component_name(identity, model_name)
        if component_key != expected_component_key:
            raise ManifestError(
                f"schema component {component_key!r} must be {expected_component_key!r}"
            )
        models.append(
            schema_to_model(
                model_name,
                schema_value,
                component_name_prefix=expected_component_key.removesuffix(model_name),
            )
        )
    return models


def schema_to_model(
    model_name: str,
    schema: Mapping[str, Any],
    *,
    component_name_prefix: str | None = None,
) -> dict[str, Any]:
    """Convert an object schema component into semantic model metadata."""
    if component_name_prefix is not None:
        validate_openapi_object_model_schema(schema, name=model_name)
    properties_value = schema.get("properties", {})
    properties = properties_value if isinstance(properties_value, Mapping) else {}
    required_names = set(string_list(schema.get("required")))
    fields: list[dict[str, Any]] = []
    for field_name, field_schema_value in properties.items():
        if not isinstance(field_name, str) or not isinstance(field_schema_value, Mapping):
            continue
        field = {
            "name": field_name,
            "type": schema_to_type_expr(
                field_schema_value,
                component_name_prefix=component_name_prefix,
            ),
            "required": field_name in required_names,
        }
        description = field_schema_value.get("description")
        if isinstance(description, str) and description:
            field["description"] = description
        fields.append(field)
    return without_none(
        {
            "name": model_name,
            "description": schema.get("description"),
            "fields": fields,
        }
    )


def validate_openapi_object_model_schema(schema: Mapping[str, Any], *, name: str) -> None:
    """Validate an OpenAPI model component keeps the UseCaseAPI object shape."""
    unsupported_keys = set(schema) - _OPENAPI_OBJECT_MODEL_SCHEMA_KEYS
    if unsupported_keys:
        raise ManifestError(
            f"object schema {name!r} has unsupported keys: {sorted(unsupported_keys)!r}"
        )
    if schema.get("type") != "object":
        raise ManifestError(f"object schema {name!r} must have type 'object'")
    if schema.get("additionalProperties") is not False:
        raise ManifestError(f"object schema {name!r} must forbid extra fields")
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        raise ManifestError(f"object schema {name!r} properties must be a mapping")
    for field_name, field_schema_value in properties.items():
        if not isinstance(field_name, str):
            raise ManifestError(f"object schema {name!r} property names must be strings")
        if not isinstance(field_schema_value, Mapping):
            raise ManifestError(f"object schema {name!r} property schemas must be mappings")
    required_value = schema.get("required", [])
    if not isinstance(required_value, list) or not all(
        isinstance(item, str) for item in required_value
    ):
        raise ManifestError(f"object schema {name!r} required must be a list of strings")
    unknown_required = set(required_value) - set(properties)
    if unknown_required:
        raise ManifestError(
            f"object schema {name!r} required fields are missing from properties: "
            f"{sorted(unknown_required)!r}"
        )


def errors_from_components(
    manifest: Mapping[str, Any],
    *,
    name: str,
    version: int,
) -> list[dict[str, Any]]:
    """Read domain error hierarchy metadata from x-usecaseapi components."""
    root_extension = required_mapping(manifest.get("x-usecaseapi"), "x-usecaseapi")
    components_value = root_extension.get("components")
    components = components_value if isinstance(components_value, Mapping) else {}
    errors_value = components.get("errors")
    errors = errors_value if isinstance(errors_value, Mapping) else {}
    identity = {"name": name, "version": version}
    prefix = component_prefix(name, version)
    result: list[dict[str, Any]] = []
    for key, metadata in errors.items():
        if not isinstance(key, str) or not isinstance(metadata, Mapping):
            continue
        error_name = required_string(metadata, "name")
        if key != component_name(identity, error_name):
            continue
        payload_ref = required_string(metadata, "payloadSchema")
        payload_schema = schema_by_ref(manifest, payload_ref)
        error = {
            "name": error_name,
            "base": required_string(metadata, "base"),
            "code": required_string(metadata, "code"),
            "description": metadata.get("description"),
            "fields": schema_to_model(
                error_name + "Payload",
                payload_schema,
                component_name_prefix=prefix,
            )["fields"],
        }
        result.append(without_none(error))
    return result


def uses_from_extension(extension: Mapping[str, Any]) -> list[str]:
    """Read declared dependency keys from operation extension metadata."""
    uses_value = extension.get("uses", {})
    if not isinstance(uses_value, Mapping):
        raise ManifestError("x-usecaseapi.uses must be a mapping")
    uses: list[str] = []
    for metadata in uses_value.values():
        if not isinstance(metadata, Mapping):
            raise ManifestError("x-usecaseapi.uses entries must be mappings")
        uses.append(required_string(metadata, "key"))
    return sorted(uses)


def schema_to_type_expr(
    schema: Mapping[str, Any],
    *,
    component_name_prefix: str | None = None,
) -> str:
    """Convert a JSON Schema fragment to a supported Python type expression."""
    validate_schema_to_type_expr_profile(schema)
    if not schema_constraint_keys(schema):
        return "Any"
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return class_name_from_component_ref(ref, component_name_prefix=component_name_prefix)
    enum = schema.get("enum")
    if isinstance(enum, list):
        return enum_schema_to_type_expr(enum)
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        return any_of_schema_to_type_expr(any_of, component_name_prefix=component_name_prefix)
    schema_type = schema.get("type")
    if schema_type == "string":
        return string_schema_to_type_expr(schema)
    if schema_type == "array":
        return array_schema_to_type_expr(schema, component_name_prefix=component_name_prefix)
    if schema_type == "object":
        return object_schema_to_type_expr(schema, component_name_prefix=component_name_prefix)
    return primitive_schema_to_type_expr(schema_type)


def validate_schema_to_type_expr_profile(schema: Mapping[str, Any]) -> None:
    """Reject JSON Schema constraints that would be lost during type-expression conversion."""
    constraint_keys = schema_constraint_keys(schema)
    if not constraint_keys:
        return
    if "$ref" in constraint_keys:
        validate_schema_keys(schema, {"$ref"}, context="schema reference")
        return
    if "enum" in constraint_keys:
        validate_schema_keys(schema, {"enum"}, context="enum schema")
        return
    if "anyOf" in constraint_keys:
        validate_schema_keys(schema, {"anyOf"}, context="anyOf schema")
        return
    schema_type = schema.get("type")
    if schema_type == "string":
        validate_string_schema_profile(schema)
        return
    if schema_type == "array":
        validate_array_schema_profile(schema)
        return
    if schema_type == "object":
        validate_object_value_schema_profile(schema)
        return
    if schema_type in _JSON_SCHEMA_PRIMITIVE_TYPES:
        validate_schema_keys(schema, {"type"}, context=f"{schema_type} schema")
        return
    primitive_schema_to_type_expr(schema_type)


def validate_schema_keys(
    schema: Mapping[str, Any], allowed_keys: set[str], *, context: str
) -> None:
    """Reject schema keys outside a supported conversion profile."""
    unsupported_keys = schema_constraint_keys(schema) - allowed_keys
    if unsupported_keys:
        raise ManifestError(f"{context} has unsupported keys: {sorted(unsupported_keys)!r}")


def validate_string_schema_profile(schema: Mapping[str, Any]) -> None:
    """Validate a string schema can be represented as a Manifest type expression."""
    validate_schema_keys(
        schema,
        {"contentEncoding", "format", "type"},
        context="string schema",
    )
    format_value = schema.get("format")
    if format_value is not None and format_value not in _JSON_SCHEMA_STRING_FORMATS:
        raise ManifestError(f"unsupported string schema format {format_value!r}")
    content_encoding = schema.get("contentEncoding")
    if content_encoding is not None and content_encoding != "base64":
        raise ManifestError(f"unsupported string schema contentEncoding {content_encoding!r}")
    if format_value is not None and content_encoding is not None:
        raise ManifestError("string schema cannot combine format and contentEncoding")


def validate_array_schema_profile(schema: Mapping[str, Any]) -> None:
    """Validate an array schema can be represented as a Manifest type expression."""
    constraint_keys = schema_constraint_keys(schema)
    if "prefixItems" in constraint_keys:
        validate_schema_keys(
            schema,
            {"maxItems", "minItems", "prefixItems", "type"},
            context="tuple schema",
        )
        prefix_items = schema.get("prefixItems")
        if not isinstance(prefix_items, list) or not prefix_items:
            raise ManifestError("tuple schema prefixItems must be a non-empty list")
        if schema.get("minItems") != len(prefix_items) or schema.get("maxItems") != len(
            prefix_items
        ):
            raise ManifestError("tuple schema minItems/maxItems must match prefixItems length")
        return
    validate_schema_keys(schema, {"items", "type", "uniqueItems"}, context="array schema")
    unique_items = schema.get("uniqueItems")
    if unique_items is not None and unique_items is not True:
        raise ManifestError("array schema uniqueItems must be true when present")


def validate_object_value_schema_profile(schema: Mapping[str, Any]) -> None:
    """Validate an object value schema can be represented as dict[str, T]."""
    validate_schema_keys(schema, {"additionalProperties", "type"}, context="object value schema")


def schema_constraint_keys(schema: Mapping[str, Any]) -> set[str]:
    """Return schema keys that affect the represented type."""
    return set(schema) - _SCHEMA_METADATA_KEYS


def enum_schema_to_type_expr(enum: Sequence[object]) -> str:
    """Convert an enum schema to a Literal type expression."""
    if not enum:
        raise ManifestError("enum schema must not be empty")
    if not all(is_supported_literal_value_object(item) for item in enum):
        raise ManifestError("enum schema values must be supported Literal values")
    return "Literal[" + ", ".join(repr(item) for item in enum) + "]"


def any_of_schema_to_type_expr(
    any_of: Sequence[object],
    *,
    component_name_prefix: str | None = None,
) -> str:
    """Convert an anyOf schema to a union type expression."""
    if not any_of or not all(isinstance(item, Mapping) for item in any_of):
        raise ManifestError("anyOf schema entries must be non-empty mappings")
    return " | ".join(
        schema_to_type_expr(
            cast(Mapping[str, Any], item),
            component_name_prefix=component_name_prefix,
        )
        for item in any_of
    )


def string_schema_to_type_expr(schema: Mapping[str, Any]) -> str:
    """Convert a string schema to a Python type expression."""
    if schema.get("contentEncoding") == "base64":
        return "bytes"
    format_value = schema.get("format")
    formats = {
        "uuid": "UUID",
        "date": "date",
        "date-time": "datetime",
        "decimal": "Decimal",
    }
    return formats.get(format_value, "str") if isinstance(format_value, str) else "str"


def primitive_schema_to_type_expr(schema_type: object) -> str:
    """Convert a primitive JSON Schema type to a Python type expression."""
    if not isinstance(schema_type, str):
        raise ManifestError("schema.type is required for non-empty schemas")
    primitives = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "null": "None",
    }
    result = primitives.get(schema_type)
    if result is None:
        raise ManifestError(f"unsupported schema type {schema_type!r}")
    return result


def array_schema_to_type_expr(
    schema: Mapping[str, Any],
    *,
    component_name_prefix: str | None = None,
) -> str:
    """Convert an array schema to a Python type expression."""
    prefix_items = schema.get("prefixItems")
    if isinstance(prefix_items, list) and prefix_items:
        if not all(isinstance(item, Mapping) for item in prefix_items):
            raise ManifestError("array prefixItems entries must be mappings")
        return (
            "tuple["
            + ", ".join(
                schema_to_type_expr(item, component_name_prefix=component_name_prefix)
                for item in prefix_items
            )
            + "]"
        )
    items = schema.get("items")
    if not isinstance(items, Mapping):
        raise ManifestError("array schema requires an items schema")
    item_type = schema_to_type_expr(items, component_name_prefix=component_name_prefix)
    if schema.get("uniqueItems") is True:
        return f"set[{item_type}]"
    return f"list[{item_type}]"


def object_schema_to_type_expr(
    schema: Mapping[str, Any],
    *,
    component_name_prefix: str | None = None,
) -> str:
    """Convert an object schema to a Python type expression."""
    additional = schema.get("additionalProperties")
    if not isinstance(additional, Mapping):
        raise ManifestError("object schema requires an additionalProperties schema")
    value_type = schema_to_type_expr(additional, component_name_prefix=component_name_prefix)
    return f"dict[str, {value_type}]"


def component_schemas(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return OpenAPI component schemas."""
    components = required_mapping(manifest.get("components"), "components")
    schemas = required_mapping(components.get("schemas"), "components.schemas")
    return schemas


def schema_by_ref(manifest: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    """Resolve a local component schema reference."""
    prefix = "#/components/schemas/"
    if not ref.startswith(prefix):
        raise ManifestError(f"unsupported schema reference {ref!r}")
    schema = component_schemas(manifest).get(ref.removeprefix(prefix))
    return required_mapping(schema, ref)


def class_name_from_component_ref(
    ref: str,
    *,
    component_name_prefix: str | None = None,
) -> str:
    """Infer the Python class name from a local schema component reference."""
    ref_prefix = "#/components/schemas/"
    if not ref.startswith(ref_prefix):
        raise ManifestError(f"unsupported schema reference {ref!r}")
    component_key = ref.removeprefix(ref_prefix)
    if component_name_prefix is None:
        return component_key
    if not component_key.startswith(component_name_prefix):
        raise ManifestError(
            f"schema reference {ref!r} must use component prefix {component_name_prefix!r}"
        )
    class_name = component_key.removeprefix(component_name_prefix)
    if not class_name:
        raise ManifestError(f"schema reference {ref!r} is missing a class name")
    if not valid_python_identifier(class_name):
        raise ManifestError(f"schema reference {ref!r} has invalid class name {class_name!r}")
    return class_name


def component_prefix(name: str, version: int) -> str:
    """Return the component key prefix for a usecase."""
    return "".join(pascal_identifier(part) for part in name.split(".")) + f"V{version}"


def pascal_identifier(value: str) -> str:
    """Return a PascalCase identifier fragment from snake_case or dotted names."""
    return "".join(part.capitalize() for part in value.split("_"))


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
    validate_type_references(item)
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
        elif not valid_python_identifier(value):
            raise ManifestError(f"usecases[{index}].source.{field_name} must be an identifier")
    implementation_class = source.get("implementation_class")
    if isinstance(implementation_class, str) and implementation_class:
        if not valid_python_identifier(implementation_class):
            raise ManifestError(
                f"usecases[{index}].source.implementation_class must be an identifier"
            )
    for field_name in ("contract_file", "implementation_file"):
        file_path = source.get(field_name)
        if isinstance(file_path, str) and file_path:
            validate_manifest_file_path(file_path, context=f"usecases[{index}].source.{field_name}")


def validate_manifest_file_path(value: str, *, context: str) -> None:
    """Validate a Manifest-provided generated Python file path."""
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ManifestError(f"{context} must not contain empty, current, or parent segments")
    path = Path(value)
    if path.is_absolute():
        raise ManifestError(f"{context} must be a relative path")
    if path.suffix != ".py":
        raise ManifestError(f"{context} must end with .py")
    module_parts = list(path.with_suffix("").parts)
    for part in module_parts:
        if not valid_python_identifier(part):
            raise ManifestError(f"{context} contains invalid Python module segment {part!r}")


def validate_contract_file_module(
    contract_path: str,
    contract_module: str,
    *,
    package: str | None,
) -> None:
    """Validate that an explicit contract file maps to the declared contract module."""
    file_module = module_from_python_file(Path(contract_path), package=package)
    if file_module != contract_module:
        raise ManifestError(
            "source.contract_file must map to source.contract_module "
            f"({file_module!r} != {contract_module!r})"
        )


def validate_models(item: Mapping[str, Any], *, index: int) -> None:
    """Validate model declarations for one usecase."""
    input_name = required_string(item, "input")
    output_name = required_string(item, "output")
    if not valid_python_identifier(input_name) or not valid_python_identifier(output_name):
        raise ManifestError(f"usecases[{index}].input/output must be identifiers")

    model_names: set[str] = set()
    for model in manifest_models(item):
        model_name = required_string(model, "name")
        if not valid_python_identifier(model_name):
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
        if not valid_python_identifier(error_name):
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


def validate_type_references(item: Mapping[str, Any]) -> None:
    """Validate that user-defined field types reference declared models."""
    model_names = {required_string(model, "name") for model in manifest_models(item)}
    for model in manifest_models(item):
        model_name = required_string(model, "name")
        for field in manifest_fields(model):
            validate_type_expr_references(
                required_string(field, "type"),
                model_names=model_names,
                context=f"model {model_name}",
            )
    for error in manifest_errors(item):
        error_name = required_string(error, "name")
        for field in manifest_fields(error):
            validate_type_expr_references(
                required_string(field, "type"),
                model_names=model_names,
                context=f"error {error_name}",
            )


def validate_type_expr_references(
    expr: str,
    *,
    model_names: set[str],
    context: str,
) -> None:
    """Validate model references inside one supported type expression."""
    parsed = ast.parse(expr, mode="eval").body

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            if node.id in _GENERIC_TYPE_NAMES:
                raise ManifestError(
                    f"generic type requires type arguments in {context}: {node.id!r}"
                )
            if node.id not in _BUILTIN_TYPE_NAMES and node.id not in model_names:
                raise ManifestError(f"unknown model type {node.id!r} in {context}")
            return
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id in _GENERIC_TYPE_NAMES:
                if node.value.id == "Literal":
                    return
                visit(node.slice)
                return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(parsed)


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


def type_expr_allows_none(expr: str) -> bool:
    """Return whether a supported type expression admits an explicit None value."""
    validate_type_expr(expr)
    parsed = ast.parse(expr, mode="eval").body

    return top_level_type_ast_allows_none(parsed)


def top_level_type_ast_allows_none(node: ast.AST) -> bool:
    """Return whether a top-level type AST admits None as the field value itself."""
    if isinstance(node, ast.Name):
        return node.id == "Any"
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return top_level_type_ast_allows_none(node.left) or top_level_type_ast_allows_none(
            node.right
        )
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        if node.value.id == "Literal":
            return any(
                isinstance(arg, ast.Constant) and arg.value is None
                for arg in subscript_args(node.slice)
            )
        return False
    return False


def validate_type_ast(node: ast.AST, *, expr: str) -> None:
    """Validate an AST node for the supported type expression subset."""
    if isinstance(node, ast.Name):
        if node.id in _GENERIC_TYPE_NAMES:
            raise ManifestError(f"generic type requires type arguments in {expr!r}: {node.id!r}")
        if not (node.id in _BUILTIN_TYPE_NAMES or node.id.isidentifier()):
            raise ManifestError(f"invalid type name in {expr!r}: {node.id!r}")
        return
    if isinstance(node, ast.Constant):
        if node.value is None:
            return
        raise ManifestError(f"invalid literal in {expr!r}")
    if isinstance(node, ast.Subscript):
        validate_subscript_type_ast(node, expr=expr)
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        validate_type_ast(node.left, expr=expr)
        validate_type_ast(node.right, expr=expr)
        return
    raise ManifestError(f"unsupported type expression syntax in {expr!r}")


def validate_subscript_type_ast(node: ast.Subscript, *, expr: str) -> None:
    """Validate supported generic type expression shapes."""
    if not isinstance(node.value, ast.Name) or node.value.id not in _GENERIC_TYPE_NAMES:
        raise ManifestError(f"unsupported generic type in {expr!r}")

    name = node.value.id
    args = subscript_args(node.slice)
    if name in {"list", "set"}:
        validate_single_argument_generic(name, args, expr=expr)
        return
    if name == "dict":
        validate_dict_generic(args, expr=expr)
        return
    if name == "tuple":
        validate_tuple_generic(args, expr=expr)
        return
    if name == "Literal":
        validate_literal_generic(args)
        return


def validate_single_argument_generic(name: str, args: Sequence[ast.AST], *, expr: str) -> None:
    """Validate list[T] and set[T] type expressions."""
    if len(args) != 1:
        raise ManifestError(f"generic type {name!r} requires exactly one argument")
    validate_type_ast(args[0], expr=expr)


def validate_dict_generic(args: Sequence[ast.AST], *, expr: str) -> None:
    """Validate dict[str, T] type expressions."""
    if len(args) != 2:
        raise ManifestError("generic type 'dict' requires exactly two arguments")
    if not (isinstance(args[0], ast.Name) and args[0].id == "str"):
        raise ManifestError("generic type 'dict' requires a str key type")
    validate_type_ast(args[1], expr=expr)


def validate_tuple_generic(args: Sequence[ast.AST], *, expr: str) -> None:
    """Validate tuple[T, U] type expressions."""
    if not args:
        raise ManifestError("generic type 'tuple' requires at least one argument")
    for arg in args:
        validate_type_ast(arg, expr=expr)


def validate_literal_generic(args: Sequence[ast.AST]) -> None:
    """Validate Literal[...] type expressions."""
    if not args:
        raise ManifestError("Literal values require at least one argument")
    for arg in args:
        if not is_supported_literal_value(arg):
            raise ManifestError("Literal values must be string, integer, float, boolean, or None")


def is_supported_literal_value(node: ast.AST) -> bool:
    """Return whether an AST node is a supported Literal[...] value."""
    if not isinstance(node, ast.Constant):
        return False
    return is_supported_literal_value_object(node.value)


def is_supported_literal_value_object(value: object) -> bool:
    """Return whether a JSON value is supported by Literal[...] fields."""
    return isinstance(value, str | int | float | bool) or value is None


def validate_field(field: Mapping[str, Any], *, context: str) -> None:
    """Validate one Manifest model or error field."""
    field_name = required_string(field, "name")
    if not valid_python_identifier(field_name):
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
    if manifest.get("kind") == LEGACY_MANIFEST_KIND or "usecases" in manifest:
        value = manifest.get("usecases")
    else:
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


def render_model_class(model: Mapping[str, Any]) -> list[str]:
    """Render a Model class from Manifest metadata."""
    name = required_string(model, "name")
    fields = manifest_fields(model)
    lines = [f"class {name}(Model):"]
    description = model.get("description")
    if isinstance(description, str) and description:
        lines.append(f"    {py_string_literal(description)}")
        lines.append("")
    if not fields:
        lines.append("    pass")
        return lines
    for field in fields:
        type_expr, default = render_scaffold_field(field, context=f"model {name}")
        lines.append(f"    {required_string(field, 'name')}: {type_expr}{default}")
    return lines


def render_scaffold_field(field: Mapping[str, Any], *, context: str) -> tuple[str, str]:
    """Return a field annotation and default without widening the Manifest contract."""
    field_name = required_string(field, "name")
    type_expr = required_string(field, "type")
    required = bool(field.get("required", True))
    if required:
        return type_expr, ""
    if not type_expr_allows_none(type_expr):
        raise ManifestError(
            f"{context}.{field_name} is optional but non-nullable; scaffold cannot preserve "
            "that contract"
        )
    return type_expr, " = None"


def render_error_class(error: Mapping[str, Any]) -> list[str]:
    """Render a UseCaseError class from Manifest metadata."""
    name = required_string(error, "name")
    base = string_or_default(error.get("base"), "UseCaseError")
    code = required_string(error, "code")
    description = error.get("description")
    class_description = (
        description if isinstance(description, str) and description else f"Domain error for {code}."
    )
    fields = manifest_fields(error)
    lines = [
        f"class {name}({base}):",
        f"    {py_string_literal(class_description)}",
        "",
        f"    code: ClassVar[str] = {py_string_literal(code)}",
    ]
    if not fields:
        return lines
    lines.append("")
    for field in fields:
        lines.append(f"    {required_string(field, 'name')}: {required_string(field, 'type')}")
    lines.append("")
    params = ", ".join(render_error_init_param(field, context=f"error {name}") for field in fields)
    lines.append(f"    def __init__(self, *, {params}) -> None:")
    lines.append(f"        {py_string_literal(f'Create a {name} domain error.')}")
    for field in fields:
        field_name = required_string(field, "name")
        lines.append(f"        self.{field_name} = {field_name}")
    lines.append(f"        super().__init__({py_string_literal(code)})")
    return lines


def render_error_init_param(field: Mapping[str, Any], *, context: str) -> str:
    """Render an error constructor parameter without changing optional/null semantics."""
    field_name = required_string(field, "name")
    type_expr, default = render_scaffold_field(field, context=context)
    return f"{field_name}: {type_expr}{default}"


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
        f"    {py_string_literal(protocol_description)}",
        "",
        f"    async def __call__(self, input: {input_name}, /) -> {output_name}:",
        f"        {py_string_literal(f'Run {name} v{version}.')}",
        "        ...",
        "",
        "",
        f"{ref}: UseCaseRef[{input_name}, {output_name}] = define_usecase(",
        f"    {protocol_class},",
        "    Contract(",
        f"        name={py_string_literal(name)},",
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


def py_string_literal(value: str) -> str:
    """Render a Python string literal for generated source."""
    return repr(value)


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


def default_manifest_test_file(usecase: Mapping[str, Any], *, tests_root: str) -> str:
    """Return the default generated pytest file path for a Manifest usecase."""
    name = required_string(usecase, "name")
    version = required_int(usecase, "version")
    parts = name.split(".")
    return str(
        Path(tests_root) / Path(*parts[:-1]) / parts[-1] / f"v{version}" / f"test_{parts[-1]}.py"
    )


def module_from_python_file(path: Path, *, package: str | None) -> str:
    """Return an import module for a generated Python file."""
    parts = list(path.with_suffix("").parts)
    if package is not None and package in parts:
        parts = parts[parts.index(package) :]
    return ".".join(parts)


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
            init_file.write_text('"""Generated package."""\n')
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
    return len(parts) >= 2 and all(
        valid_python_identifier(part) and part.islower() for part in parts
    )


def valid_key(key: str) -> bool:
    """Return whether a usecase key is valid."""
    if "@v" not in key:
        return False
    name, _, version = key.partition("@v")
    return valid_contract_name(name) and version.isdigit() and int(version) >= 1


def valid_module_path(value: str) -> bool:
    """Return whether a dotted Python module path is valid."""
    return bool(value) and all(valid_python_identifier(part) for part in value.split("."))


def valid_python_identifier(value: str) -> bool:
    """Return whether a value is a Python identifier that can be generated safely."""
    return value.isidentifier() and not keyword.iskeyword(value)


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


def without_none(value: dict[str, Any], *, preserve_empty: bool = False) -> dict[str, Any]:
    """Return a copy without None values, including nested mappings."""
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            nested = without_none(item, preserve_empty=preserve_empty or key == "properties")
            if nested or key == "properties" or key in _EMPTY_SCHEMA_KEYS or preserve_empty:
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
        layout = semantic_from_openapi_manifest(manifest).get("layout")
    else:
        layout = manifest.get("layout")
    package = layout.get("package") if isinstance(layout, Mapping) else None
    if isinstance(package, str):
        return package
    return None
