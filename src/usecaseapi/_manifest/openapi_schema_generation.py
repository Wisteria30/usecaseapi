"""JSON Schema generation for UseCaseAPI OpenAPI components."""

from __future__ import annotations

import ast

from collections.abc import Mapping, Sequence
from typing import Any

from .accessors import manifest_fields
from .helpers import (
    required_int,
    required_string,
    subscript_args,
    without_none,
)
from .openapi_naming import (
    component_name,
    component_ref,
    schema_kind,
)
from .semantic_validation import validate_type_expr


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
