"""Development-only Swagger preview support."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "._swagger.app": (
        "create_swagger_app",
        "domain_error_envelope",
        "is_port_available",
        "load_composition_graph",
        "load_preview",
        "make_usecase_endpoint",
        "preview_context_from_module",
        "preview_operation_id",
        "preview_route_name",
        "preview_route_path",
        "raise_missing_preview_target_error",
        "raise_preview_export_error",
        "register_domain_error_handler",
        "resolve_context",
        "select_available_port",
        "serve_swagger_preview",
    ),
    "._swagger.discovery": (
        "API_EXPORT_NAMES",
        "AUTO_DISCOVERY_EXCLUDED_DIRS",
        "FACTORY_EXPORT_NAMES",
        "PREVIEW_MODULE_CANDIDATES",
        "PreviewConfig",
        "PreviewTargetCandidate",
        "SwaggerPreviewError",
        "discover_composition_targets",
        "discover_preview_module",
        "discover_preview_module_or_none",
        "discover_preview_target",
        "looks_like_usecaseapi_composition",
        "module_name_from_path",
        "preview_target_score",
        "project_import_roots",
        "should_skip_auto_discovery_path",
    ),
    "._swagger.imports": (
        "callable_accepts_no_required_arguments",
        "import_preview_file",
        "import_preview_module",
        "import_preview_module_name",
        "import_preview_target",
        "preview_api_from_module",
        "preview_api_from_value",
        "preview_runtime_import_roots",
        "split_preview_export",
    ),
}

for _module_name, _names in _EXPORTS.items():
    _module = import_module(_module_name, package=__package__)
    for _name in _names:
        globals()[_name] = getattr(_module, _name)

__all__ = tuple(name for names in _EXPORTS.values() for name in names)

del import_module, _module, _module_name, _name, _names
