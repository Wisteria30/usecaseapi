"""Manifest implementation package."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

import ast

from collections.abc import Mapping, Sequence
from typing import Any

from .common import *


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
