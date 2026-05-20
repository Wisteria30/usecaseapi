"""JSON Schema to Manifest type-expression conversion."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from .common import *
from .semantic_validation import *


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
        from .openapi_components import class_name_from_component_ref

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


__all__ = [name for name in globals() if not name.startswith("__")]
