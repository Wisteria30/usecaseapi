"""Development-only Swagger preview support."""

from __future__ import annotations

import ast
import base64
import importlib
import importlib.util
import inspect
import re
import socket
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
    Path("tests/usecaseapi_preview.py"),
    Path("dev/usecaseapi_preview.py"),
    Path("src/composition.py"),
    Path("composition.py"),
    Path("usecaseapi_preview.py"),
    Path("preview.py"),
)
API_EXPORT_NAMES = ("api", "usecases")
FACTORY_EXPORT_NAMES = ("create_api", "create_usecases")
ROUTE_SAFE_CONTRACT_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
AUTO_DISCOVERY_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "docs",
    "htmlcov",
    "tests",
}


class SwaggerPreviewError(UseCaseAPIError):
    """Raised when a Swagger preview module cannot be discovered or loaded."""


@dataclass(frozen=True, slots=True)
class PreviewConfig:
    """Loaded Swagger preview module configuration."""

    api: UseCaseAPI[Any]
    create_context: Callable[..., Any] | None
    module: ModuleType


@dataclass(frozen=True, slots=True)
class PreviewTargetCandidate:
    """Importable preview target discovered from project composition code."""

    target: str
    path: Path
    score: tuple[int, int]


def discover_preview_module(*, cwd: Path | None = None) -> Path:
    """Discover the first supported preview module path under a working directory."""
    root = Path.cwd() if cwd is None else cwd
    for candidate in PREVIEW_MODULE_CANDIDATES:
        path = root / candidate
        if path.is_file():
            return path
    expected = ", ".join(str(candidate) for candidate in PREVIEW_MODULE_CANDIDATES)
    raise SwaggerPreviewError(f"could not find preview module; expected one of: {expected}")


def discover_preview_target(*, cwd: Path | None = None) -> str:
    """Discover the best preview target from explicit files or project composition code."""
    root = Path.cwd() if cwd is None else cwd
    try:
        return str(discover_preview_module(cwd=root))
    except SwaggerPreviewError:
        pass

    candidates = discover_composition_targets(cwd=root)
    if not candidates:
        expected = ", ".join(str(candidate) for candidate in PREVIEW_MODULE_CANDIDATES)
        raise SwaggerPreviewError(
            "could not find preview target; expected one of: "
            f"{expected}; or an importable composition module under src/ or the project root"
        )

    first = candidates[0]
    tied = [candidate for candidate in candidates if candidate.score == first.score]
    if len(tied) > 1:
        choices = ", ".join(candidate.target for candidate in tied)
        raise SwaggerPreviewError(
            f"found multiple equally likely preview targets; specify one with --preview: {choices}"
        )
    return first.target


def discover_composition_targets(*, cwd: Path | None = None) -> list[PreviewTargetCandidate]:
    """Return importable composition targets that look like UseCaseAPI compositions."""
    root = Path.cwd() if cwd is None else cwd
    candidates: list[PreviewTargetCandidate] = []
    seen_paths: set[Path] = set()
    for import_root in project_import_roots(root):
        for path in import_root.rglob("composition.py"):
            resolved = path.resolve()
            if resolved in seen_paths or should_skip_auto_discovery_path(path, import_root):
                continue
            seen_paths.add(resolved)
            module_name = module_name_from_path(path, import_root)
            if module_name is None or not looks_like_usecaseapi_composition(path):
                continue
            candidates.append(
                PreviewTargetCandidate(
                    target=module_name,
                    path=path,
                    score=preview_target_score(module_name),
                )
            )
    return sorted(candidates, key=lambda candidate: (*candidate.score, candidate.target))


def project_import_roots(root: Path) -> tuple[Path, ...]:
    """Return import roots used for no-config preview discovery."""
    src = root / "src"
    if src.is_dir():
        return (src, root)
    return (root,)


def should_skip_auto_discovery_path(path: Path, import_root: Path) -> bool:
    """Return whether a candidate path is outside ordinary project source code."""
    try:
        parts = path.relative_to(import_root).parts
    except ValueError:
        return True
    if import_root.name != "src" and parts and parts[0] == "src":
        return True
    return any(part in AUTO_DISCOVERY_EXCLUDED_DIRS for part in parts)


def module_name_from_path(path: Path, import_root: Path) -> str | None:
    """Return the import module name for a Python file under an import root."""
    try:
        relative = path.relative_to(import_root).with_suffix("")
    except ValueError:
        return None
    parts = relative.parts
    if not parts or not all(part.isidentifier() for part in parts):
        return None
    return ".".join(parts)


def looks_like_usecaseapi_composition(path: Path) -> bool:
    """Return whether a composition file exposes or can create a UseCaseAPI instance."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in (
            *FACTORY_EXPORT_NAMES,
            *API_EXPORT_NAMES,
        ):
            return True
        if isinstance(node, ast.AnnAssign):
            annotated_target = node.target
            if isinstance(annotated_target, ast.Name) and annotated_target.id in API_EXPORT_NAMES:
                return True
        if isinstance(node, ast.Assign):
            for assigned_target in node.targets:
                if isinstance(assigned_target, ast.Name) and assigned_target.id in API_EXPORT_NAMES:
                    return True
    return False


def preview_target_score(module_name: str) -> tuple[int, int]:
    """Return the deterministic ranking for automatically discovered preview targets."""
    parts = module_name.split(".")
    first = parts[0]
    if first in {"app", "app_shell", "application"}:
        category = 0
    elif module_name == "composition":
        category = 1
    elif first == "packages":
        category = 3
    else:
        category = 2
    return category, len(parts)


def load_preview(preview: str | None) -> PreviewConfig:
    """Load a Swagger preview module and validate its exported configuration."""
    module, export_name = import_preview_target(preview)
    api = preview_api_from_module(module, export_name=export_name)
    if not isinstance(api, UseCaseAPI):
        exports = "', '".join((*API_EXPORT_NAMES, *FACTORY_EXPORT_NAMES))
        raise SwaggerPreviewError(
            f"preview module must export one of '{exports}' as a UseCaseAPI instance "
            "or a zero-argument factory returning one"
        )
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
    selected_port = select_available_port(host=host, preferred_port=port)
    print("UseCaseAPI Swagger preview running at:")
    if selected_port != port:
        print(f"  requested port {port} is unavailable; using {selected_port}")
    print(f"  http://{host}:{selected_port}/docs")
    uvicorn.run(app, host=host, port=selected_port)


def select_available_port(*, host: str, preferred_port: int) -> int:
    """Return the first available TCP port at or above the preferred port."""
    for port in range(preferred_port, 65536):
        if is_port_available(host=host, port=port):
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
    return f"/_usecases/{preview_route_name(ref.contract.name)}/v{ref.contract.version}/call"


def preview_route_name(contract_name: str) -> str:
    """Return a URL-safe route segment for a contract name."""
    if ROUTE_SAFE_CONTRACT_NAME.fullmatch(contract_name):
        return contract_name
    encoded = base64.urlsafe_b64encode(contract_name.encode()).decode().rstrip("=")
    return f"~{encoded}"


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
    from fastapi import Header, Request

    async def endpoint(
        input: Any,
        request: Request,
        *,
        _x_usecaseapi_scenario: str | None = None,
    ) -> Any:
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


def import_preview_module(preview: str | None) -> ModuleType:
    """Import a preview module from discovery, a file path, or a module name."""
    module, _ = import_preview_target(preview)
    return module


def import_preview_target(preview: str | None) -> tuple[ModuleType, str | None]:
    """Import a preview target and return its optional explicit export name."""
    if preview is None:
        preview = discover_preview_target()

    module_name, export_name = split_preview_export(preview)
    if export_name is not None:
        return import_preview_module_name(module_name), export_name

    path = Path(preview)
    if path.suffix == ".py" or path.exists():
        if not path.is_file():
            raise SwaggerPreviewError(f"preview path {preview!r} is not a file")
        return import_preview_file(path), None

    return import_preview_module_name(preview), None


def split_preview_export(preview: str) -> tuple[str, str | None]:
    """Split a module:export preview target without treating file paths as modules."""
    if preview.endswith(".py") or Path(preview).exists() or ":" not in preview:
        return preview, None
    module_name, export_name = preview.rsplit(":", 1)
    if not module_name or not export_name:
        raise SwaggerPreviewError(f"invalid preview target: {preview}")
    return module_name, export_name


def import_preview_module_name(preview: str) -> ModuleType:
    """Import a preview module name with ordinary project import roots available."""
    roots = [str(path.resolve()) for path in project_import_roots(Path.cwd())]
    added_roots = [root for root in roots if root not in sys.path]
    sys.path[:0] = added_roots
    try:
        return importlib.import_module(preview)
    except ModuleNotFoundError as exc:
        if exc.name == preview or (exc.name is not None and preview.startswith(exc.name + ".")):
            raise SwaggerPreviewError(f"preview module does not exist: {preview}") from exc
        raise
    finally:
        for root in reversed(added_roots):
            sys.path.remove(root)


def preview_api_from_module(
    module: ModuleType, *, export_name: str | None
) -> UseCaseAPI[Any] | None:
    """Return a UseCaseAPI instance from a module export or supported factory."""
    export_names = (export_name,) if export_name is not None else API_EXPORT_NAMES
    for name in export_names:
        value = getattr(module, name, None)
        api = preview_api_from_value(value)
        if api is not None:
            return api
    if export_name is None:
        for name in FACTORY_EXPORT_NAMES:
            value = getattr(module, name, None)
            api = preview_api_from_value(value)
            if api is not None:
                return api
    return None


def preview_api_from_value(value: Any) -> UseCaseAPI[Any] | None:
    """Return a UseCaseAPI instance from a value or zero-argument factory."""
    if isinstance(value, UseCaseAPI):
        return value
    if not callable(value) or not callable_accepts_no_required_arguments(value):
        return None
    result = value()
    if isinstance(result, UseCaseAPI):
        return result
    return None


def callable_accepts_no_required_arguments(value: Callable[..., Any]) -> bool:
    """Return whether a callable can be invoked without user-provided arguments."""
    if inspect.iscoroutinefunction(value):
        return False
    try:
        signature = inspect.signature(value)
    except (TypeError, ValueError):
        return False
    return all(
        parameter.default is not inspect.Parameter.empty
        or parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
        for parameter in signature.parameters.values()
    )


def import_preview_file(path: Path) -> ModuleType:
    """Import a preview module from a Python file path."""
    resolved = path.resolve()
    module_name = f"_usecaseapi_swagger_preview_{abs(hash(resolved))}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise SwaggerPreviewError(f"could not create import loader for preview file {resolved}")

    roots = [
        str(resolved.parent),
        *(str(path.resolve()) for path in project_import_roots(Path.cwd())),
    ]
    added_roots = [
        root
        for index, root in enumerate(roots)
        if root not in sys.path and root not in roots[:index]
    ]
    sys.path[:0] = added_roots
    try:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
    finally:
        for root in reversed(added_roots):
            sys.path.remove(root)
    return module
