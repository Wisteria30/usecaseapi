"""OpenAPI profile naming helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .helpers import (
    pascal_identifier,
    required_int,
    required_string,
)


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
