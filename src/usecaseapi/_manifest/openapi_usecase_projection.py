"""Projection from OpenAPI operations to semantic usecase metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .common import (
    LEGACY_MANIFEST_KIND,
    PROTOCOL_KIND,
    ManifestError,
)
from .helpers import (
    required_int,
    required_mapping,
    required_string,
    string_list,
    string_or_default,
    without_none,
)
from .openapi_components import (
    errors_from_components,
    models_from_components,
    uses_from_extension,
)
from .openapi_operation_validation import (
    validate_openapi_operation_contract_schemas,
    validate_openapi_operation_extension,
    validate_openapi_operation_identity,
    validate_openapi_operation_shape,
    validate_openapi_path_item,
)


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
