"""Development-only Swagger preview support."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .api import UseCaseAPI
from .contracts import UseCaseRef
from .errors import UseCaseAPIError

PREVIEW_MODULE_CANDIDATES = (
    Path("usecaseapi_preview.py"),
    Path("preview.py"),
    Path("composition.py"),
    Path("src/composition.py"),
)


class SwaggerPreviewError(UseCaseAPIError):
    """Raised when a Swagger preview module cannot be discovered or loaded."""


@dataclass(frozen=True, slots=True)
class PreviewConfig:
    """Loaded Swagger preview module configuration."""

    api: UseCaseAPI[Any]
    create_context: Callable[..., Any] | None
    module: ModuleType


def discover_preview_module(*, cwd: Path | None = None) -> Path:
    """Discover the first supported preview module path under a working directory."""
    root = Path.cwd() if cwd is None else cwd
    for candidate in PREVIEW_MODULE_CANDIDATES:
        path = root / candidate
        if path.is_file():
            return path
    expected = ", ".join(str(candidate) for candidate in PREVIEW_MODULE_CANDIDATES)
    raise SwaggerPreviewError(f"could not find preview module; expected one of: {expected}")


def load_preview(preview: str | None) -> PreviewConfig:
    """Load a Swagger preview module and validate its exported configuration."""
    module = import_preview_module(preview)
    api = getattr(module, "api", None)
    if not isinstance(api, UseCaseAPI):
        raise SwaggerPreviewError("preview module must export 'api' as a UseCaseAPI instance")
    create_context = getattr(module, "create_context", None)
    if create_context is not None and not callable(create_context):
        raise SwaggerPreviewError("preview module export 'create_context' must be callable")
    return PreviewConfig(api=api, create_context=create_context, module=module)


def create_swagger_app(
    *,
    api: UseCaseAPI[Any],
    create_context: Callable[..., Any] | None,
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

    for binding in api.bindings:
        ref = binding.ref
        app.post(
            preview_route_path(ref),
            name=ref.contract.name,
            operation_id=preview_operation_id(ref),
            response_model=ref.contract.output,
        )(make_usecase_endpoint(api=api, ref=ref, create_context=create_context))

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
    app = create_swagger_app(api=config.api, create_context=config.create_context)
    print("UseCaseAPI Swagger preview running at:")
    print(f"  http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port)


def register_domain_error_handler(app: Any) -> None:
    """Register the preview JSON response for contracted domain errors."""
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    from .errors import UseCaseError

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
    return f"/_usecases/{ref.contract.name}/v{ref.contract.version}/call"


def preview_operation_id(ref: UseCaseRef[Any, Any]) -> str:
    """Return the OpenAPI operation id used by the preview app."""
    return ref.contract.name.replace(".", "_") + f"_v{ref.contract.version}_call"


def make_usecase_endpoint(
    *,
    api: UseCaseAPI[Any],
    ref: UseCaseRef[Any, Any],
    create_context: Callable[..., Any] | None,
) -> Callable[..., Awaitable[Any]]:
    """Create one FastAPI endpoint function for a bound usecase."""
    from fastapi import Request

    async def endpoint(input: Any, request: Request) -> Any:
        context = await resolve_context(create_context, request)
        return await api.caller(context).call(ref, input)

    endpoint.__name__ = preview_operation_id(ref)
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


def import_preview_module(preview: str | None) -> ModuleType:
    """Import a preview module from discovery, a file path, or a module name."""
    if preview is None:
        return import_preview_file(discover_preview_module())

    path = Path(preview)
    if path.suffix == ".py" or path.exists():
        if not path.is_file():
            raise SwaggerPreviewError(f"preview path {preview!r} is not a file")
        return import_preview_file(path)

    try:
        return importlib.import_module(preview)
    except ModuleNotFoundError as exc:
        if exc.name == preview or (exc.name is not None and preview.startswith(exc.name + ".")):
            raise SwaggerPreviewError(f"preview module does not exist: {preview}") from exc
        raise


def import_preview_file(path: Path) -> ModuleType:
    """Import a preview module from a Python file path."""
    resolved = path.resolve()
    module_name = f"_usecaseapi_swagger_preview_{abs(hash(resolved))}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise SwaggerPreviewError(f"could not create import loader for preview file {resolved}")

    parent = str(resolved.parent)
    added_parent = parent not in sys.path
    if added_parent:
        sys.path.insert(0, parent)
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
    finally:
        if added_parent:
            sys.path.remove(parent)
    return module
