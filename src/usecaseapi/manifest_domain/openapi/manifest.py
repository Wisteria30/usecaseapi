"""OpenAPI Manifest generation for the UseCaseAPI profile."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from usecaseapi.manifest_domain.common import (
    _OPENAPI_JSON_SCHEMA_DIALECT,
    MANIFEST_PROFILE_KIND,
    OPENAPI_VERSION,
    PROTOCOL_KIND,
    USECASEAPI_PROFILE,
    USECASEAPI_VERSION,
    ManifestError,
)
from usecaseapi.manifest_domain.openapi.naming import (
    component_name,
    component_ref,
    component_ref_path,
    dependency_name,
    error_component_name,
    error_envelope_component_name,
    error_payload_component_name,
    operation_id,
    response_component_name,
    response_description,
    usecase_operation_path,
)
from usecaseapi.manifest_domain.openapi.schema_generation import (
    error_envelope_schema,
    error_payload_schema,
    model_schema,
)
from usecaseapi.manifest_domain.semantic.accessors import (
    manifest_errors,
    manifest_models,
    usecase_items_from_semantic,
)
from usecaseapi.manifest_domain.semantic.catalog import (
    project_name_from_semantic,
    usecase_key,
)
from usecaseapi.manifest_domain.shared.helpers import (
    required_int,
    required_mapping,
    required_string,
    string_list,
    string_or_default,
    without_none,
)


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
