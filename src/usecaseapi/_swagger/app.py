"""FastAPI Swagger preview app and runtime loading."""
# mypy: ignore-errors

from __future__ import annotations

import inspect
import socket
import sys

from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any, NoReturn

from usecaseapi.api import UseCaseAPI
from usecaseapi.contracts import UseCaseRef
from usecaseapi.swagger_graph import (
    PreviewGraph,
    build_preview_graph,
    operation_segment,
    resolve_visible_graphs,
    route_groups_for_graphs,
    route_segment,
)

from .discovery import (
    API_EXPORT_NAMES,
    FACTORY_EXPORT_NAMES,
    PREVIEW_MODULE_CANDIDATES,
    PreviewConfig,
    PreviewTargetCandidate,
    SwaggerPreviewError,
    discover_composition_targets,
    discover_preview_module_or_none,
)
from .imports import (
    import_preview_file,
    import_preview_module_name,
    import_preview_target,
    preview_api_from_module,
)


def load_preview(preview: str | None) -> PreviewConfig:
    """Load Swagger preview graphs and validate their exported configuration."""
    if preview is not None:
        module, export_name = import_preview_target(preview)
        api = preview_api_from_module(module, export_name=export_name)
        if api is None:
            raise_preview_export_error()
        return PreviewConfig(
            graphs=(
                build_preview_graph(
                    target=preview,
                    api=api,
                    create_context=preview_context_from_module(module),
                ),
            )
        )

    preview_path = discover_preview_module_or_none()
    if preview_path is not None:
        module = import_preview_file(preview_path)
        api = preview_api_from_module(module, export_name=None)
        if api is None:
            raise_preview_export_error()
        return PreviewConfig(
            graphs=(
                build_preview_graph(
                    target=str(preview_path),
                    api=api,
                    create_context=preview_context_from_module(module),
                ),
            )
        )

    candidates = discover_composition_targets()
    if not candidates:
        raise_missing_preview_target_error()
    graphs = [load_composition_graph(candidate) for candidate in candidates]
    return PreviewConfig(graphs=tuple(resolve_visible_graphs(graphs)))


def preview_context_from_module(module: ModuleType) -> Callable[..., Any] | None:
    """Return the optional request context factory exported by a preview module."""
    create_context = getattr(module, "create_context", None)
    if create_context is not None and not callable(create_context):
        raise SwaggerPreviewError("preview module export 'create_context' must be callable")
    return create_context


def raise_preview_export_error() -> NoReturn:
    """Raise the common error for missing preview UseCaseAPI exports."""
    exports = "', '".join((*API_EXPORT_NAMES, *FACTORY_EXPORT_NAMES))
    raise SwaggerPreviewError(
        f"preview module must export one of '{exports}' as a UseCaseAPI instance "
        "or a zero-argument factory returning one"
    )


def raise_missing_preview_target_error() -> NoReturn:
    """Raise the common error for projects without any preview target."""
    expected = ", ".join(str(candidate) for candidate in PREVIEW_MODULE_CANDIDATES)
    raise SwaggerPreviewError(
        "could not find preview target; expected one of: "
        f"{expected}; or an importable composition module under src/ or the project root"
    )


def load_composition_graph(candidate: PreviewTargetCandidate) -> PreviewGraph:
    """Import a discovered composition target and build its preview graph."""
    module = import_preview_module_name(candidate.target)
    api = preview_api_from_module(module, export_name=None)
    if api is None:
        raise_preview_export_error()
    return build_preview_graph(
        target=candidate.target,
        api=api,
        create_context=preview_context_from_module(module),
    )


def create_swagger_app(
    *,
    graphs: tuple[PreviewGraph, ...],
) -> Any:
    """Create the development FastAPI preview app."""
    try:
        from fastapi import FastAPI
        from fastapi.responses import PlainTextResponse
    except ImportError as exc:
        raise SwaggerPreviewError(
            "FastAPI preview support is not installed. Install it with: uv sync --extra swagger"
        ) from exc

    app = FastAPI(
        title="UseCaseAPI Swagger Preview",
        version="0.1.0",
        description="Development-only preview server for bound UseCaseAPI usecases.",
    )
    register_domain_error_handler(app)

    @app.exception_handler(SwaggerPreviewError)
    async def swagger_preview_error_handler(_: Any, exc: SwaggerPreviewError) -> PlainTextResponse:
        return PlainTextResponse(str(exc), status_code=500)

    for group in route_groups_for_graphs(list(graphs)):
        app.post(
            group.path,
            name=group.ref.contract.name,
            operation_id=group.operation_id,
            response_model=group.ref.contract.output,
            tags=list(group.tags),
        )(
            make_usecase_endpoint(
                api=group.graph.api,
                ref=group.ref,
                create_context=group.graph.create_context,
                operation_id=group.operation_id,
            )
        )

    return app


def serve_swagger_preview(*, preview: str | None, host: str, port: int) -> None:
    """Start the blocking development Swagger preview server."""
    try:
        import uvicorn
    except ImportError as exc:
        raise SwaggerPreviewError(
            "Uvicorn preview support is not installed. Install it with: uv sync --extra swagger"
        ) from exc

    config = load_preview(preview)
    app = create_swagger_app(graphs=config.graphs)
    selected_port = select_available_port(host=host, preferred_port=port)
    print("UseCaseAPI Swagger preview running at:")
    if selected_port != port:
        print(f"  requested port {port} is unavailable; using {selected_port}")
    print(f"  http://{host}:{selected_port}/docs")
    uvicorn.run(app, host=host, port=selected_port)


def select_available_port(*, host: str, preferred_port: int) -> int:
    """Return the first available TCP port at or above the preferred port."""
    public_module = sys.modules.get("usecaseapi.swagger")
    port_available = getattr(public_module, "is_port_available", is_port_available)
    for port in range(preferred_port, 65536):
        if port_available(host=host, port=port):
            return port
    raise SwaggerPreviewError(f"could not find an available port at or above {preferred_port}")


def is_port_available(*, host: str, port: int) -> bool:
    """Return whether a TCP port can be bound by the preview server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def register_domain_error_handler(app: Any) -> None:
    """Register the preview JSON response for contracted domain errors."""
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    from usecaseapi.errors import UseCaseError

    @app.exception_handler(UseCaseError)  # type: ignore[untyped-decorator]
    async def domain_error_handler(_: Any, exc: UseCaseError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=jsonable_encoder(domain_error_envelope(exc)),
        )


def domain_error_envelope(error: Any) -> dict[str, Any]:
    """Return the explicit JSON envelope for a domain error."""
    return {
        "code": error.code,
        "error": type(error).__name__,
        "message": str(error),
        "payload": dict(error.details),
    }


def preview_route_path(ref: UseCaseRef[Any, Any]) -> str:
    """Return the canonical preview route path for a usecase."""
    return f"/_usecases/{route_segment(ref.contract.name)}/v{ref.contract.version}/call"


def preview_route_name(contract_name: str) -> str:
    """Return a URL-safe route segment for a contract name."""
    return route_segment(contract_name)


def preview_operation_id(ref: UseCaseRef[Any, Any]) -> str:
    """Return the OpenAPI operation id used by the preview app."""
    return operation_segment(ref.contract.name) + f"_v{ref.contract.version}_call"


def make_usecase_endpoint(
    *,
    api: UseCaseAPI[Any],
    ref: UseCaseRef[Any, Any],
    create_context: Callable[..., Any] | None,
    operation_id: str,
) -> Callable[..., Awaitable[Any]]:
    """Create one FastAPI endpoint function for a bound usecase."""
    from fastapi import Header, Request

    async def endpoint(
        input: Any,
        request: Request,
        *,
        _x_usecaseapi_scenario: str | None = None,
    ) -> Any:
        context = await resolve_context(create_context, request)
        return await api.caller(context).call(ref, input)

    endpoint.__name__ = operation_id
    endpoint.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        parameters=[
            inspect.Parameter(
                "input",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=ref.contract.input,
            ),
            inspect.Parameter(
                "request",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Request,
            ),
            inspect.Parameter(
                "_x_usecaseapi_scenario",
                inspect.Parameter.KEYWORD_ONLY,
                default=Header(default=None, alias="x-usecaseapi-scenario"),
                annotation=str | None,
            ),
        ],
        return_annotation=ref.contract.output,
    )
    return endpoint


async def resolve_context(create_context: Callable[..., Any] | None, request: Any) -> Any:
    """Create the per-request context used by UseCaseAPI."""
    if create_context is None:
        return None

    signature = inspect.signature(create_context)
    positional_parameters = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    keyword_only_parameters = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    ]
    required_positional_parameters = [
        parameter
        for parameter in positional_parameters
        if parameter.default is inspect.Parameter.empty
    ]
    required_keyword_only_parameters = [
        parameter
        for parameter in keyword_only_parameters
        if parameter.default is inspect.Parameter.empty
    ]

    if not required_positional_parameters and not required_keyword_only_parameters:
        value = create_context()
    elif len(required_positional_parameters) == 1 and not required_keyword_only_parameters:
        value = create_context(request)
    elif (
        not required_positional_parameters
        and len(required_keyword_only_parameters) == 1
        and required_keyword_only_parameters[0].name == "request"
    ):
        value = create_context(request=request)
    else:
        raise SwaggerPreviewError(
            "create_context must accept zero arguments or one request argument"
        )
    if inspect.isawaitable(value):
        return await value
    return value


__all__ = [name for name in globals() if not name.startswith("__")]
