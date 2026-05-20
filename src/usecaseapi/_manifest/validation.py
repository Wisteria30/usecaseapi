"""Manifest implementation package."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

import yaml

from .common import *
from .openapi import *


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
