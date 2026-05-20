"""Validation for per-usecase OpenAPI operation contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from usecaseapi.manifest_domain.common import (
    _OPENAPI_JSON_CONTENT_KEYS,
    _OPENAPI_LIFECYCLE_KEYS,
    _OPENAPI_MEDIA_TYPE_KEYS,
    _OPENAPI_OPERATION_CONTEXT_KEYS,
    _OPENAPI_OPERATION_EXTENSION_KEYS,
    _OPENAPI_OPERATION_KEYS,
    _OPENAPI_OPERATION_SEMANTICS,
    _OPENAPI_PATH_ITEM_KEYS,
    _OPENAPI_REQUEST_BODY_KEYS,
    _OPENAPI_RESPONSE_KEYS,
    PROTOCOL_KIND,
    ManifestError,
)
from usecaseapi.manifest_domain.openapi.components import schema_by_ref
from usecaseapi.manifest_domain.openapi.naming import (
    component_name,
    component_ref_path,
    dependency_name,
    operation_id,
    response_component_name,
)
from usecaseapi.manifest_domain.shared.helpers import (
    required_mapping,
    required_string,
    string_list,
)


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
