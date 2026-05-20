"""OpenAPI component schema and error metadata readers."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .common import *
from .common import _OPENAPI_OBJECT_MODEL_SCHEMA_KEYS
from .helpers import *
from .json_schema_types import *
from .openapi_naming import *


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


__all__ = [name for name in globals() if not name.startswith("__")]
