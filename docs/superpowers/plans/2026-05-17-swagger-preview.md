# Swagger Preview Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a development-only `usecaseapi swagger` command that starts a FastAPI Swagger UI and lets users execute bound UseCaseAPI usecases through `Try it out`.

**Architecture:** Add a focused `usecaseapi.swagger` module that owns preview module discovery, FastAPI route creation, request-specific context resolution, and domain error envelope serialization. Keep FastAPI/Uvicorn as optional preview dependencies loaded lazily from the CLI so UseCaseAPI's core runtime remains same-process and HTTP-free by default.

**Tech Stack:** Python 3.12+, Typer, Pydantic v2, optional FastAPI, optional Uvicorn, FastAPI TestClient via dev dependencies.

---

## File Structure

- Create `src/usecaseapi/swagger.py`
  - Owns all preview server behavior.
  - Defines `SwaggerPreviewError`, preview module loading, context factory resolution, FastAPI app creation, and blocking Uvicorn serving.
- Modify `src/usecaseapi/cli.py`
  - Adds `usecaseapi swagger`.
  - Keeps dependency import errors user-facing and explicit.
- Modify `pyproject.toml`
  - Adds `swagger` optional dependency group.
  - Adds FastAPI, Uvicorn, and HTTPX to `dev` so ordinary test runs can cover the preview feature.
- Modify `uv.lock`
  - Update via `uv lock`.
- Create `tests/test_swagger_preview.py`
  - Covers discovery, app creation, success calls, request-aware context, domain error envelopes, and CLI behavior.
- Create `examples/basic/usecaseapi_preview.py`
  - Demonstrates the convention and scenario switching.
- Modify `examples/basic/README.md`
  - Documents how to run the preview locally.
- Create `docs/swagger-preview.md`
  - Documents the development-only command, preview module convention, context factory, and scenario switching.
- Modify `README.md`
  - Links to the Swagger preview guide.

## Task 1: Add Optional Dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Add dependency groups**

Edit `pyproject.toml`:

```toml
[project.optional-dependencies]
swagger = [
  "fastapi>=0.115,<1",
  "uvicorn>=0.30,<1",
]
dev = [
  "pytest>=9.0.1",
  "mypy>=1.18.2",
  "ruff>=0.14.6",
  "build>=1.3.0",
  "coverage>=7.12.0",
  "twine>=6.2.0",
  "types-pyyaml>=6.0.12",
  "fastapi>=0.115,<1",
  "uvicorn>=0.30,<1",
  "httpx>=0.27,<1",
]
```

- [ ] **Step 2: Refresh lockfile**

Run:

```bash
uv lock
```

Expected: lockfile resolves with FastAPI, Starlette, Uvicorn, and HTTPX.

- [ ] **Step 3: Verify dependency metadata**

Run:

```bash
uv run python - <<'PY'
import tomllib
from pathlib import Path
data = tomllib.loads(Path("pyproject.toml").read_text())
print(data["project"]["optional-dependencies"]["swagger"])
PY
```

Expected output includes:

```text
['fastapi>=0.115,<1', 'uvicorn>=0.30,<1']
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add swagger preview dependencies"
```

## Task 2: Add Preview Module Discovery

**Files:**
- Create: `src/usecaseapi/swagger.py`
- Test: `tests/test_swagger_preview.py`

- [ ] **Step 1: Write failing discovery tests**

Create `tests/test_swagger_preview.py` with:

```python
"""Swagger preview behavior tests."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pytest

from usecaseapi import Contract, Model, UseCase, UseCaseAPI, define_usecase
from usecaseapi.swagger import (
    SwaggerPreviewError,
    discover_preview_module,
    load_preview,
)


class PreviewInput(Model):
    value: int


class PreviewOutput(Model):
    value: int


class PreviewUseCase(UseCase[PreviewInput, PreviewOutput], Protocol):
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        ...


PREVIEW_USECASE = define_usecase(
    PreviewUseCase,
    Contract(
        name="preview.run",
        version=1,
        input=PreviewInput,
        output=PreviewOutput,
    ),
)


class PreviewImpl:
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        return PreviewOutput(value=input.value + 1)


def test_discovers_usecaseapi_preview_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preview discovery prefers usecaseapi_preview.py in the working directory."""
    preview_file = tmp_path / "usecaseapi_preview.py"
    preview_file.write_text(
        "from usecaseapi import UseCaseAPI\n"
        "api = UseCaseAPI[None]()\n",
    )
    monkeypatch.chdir(tmp_path)

    discovered = discover_preview_module()

    assert discovered == preview_file


def test_load_preview_requires_api_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preview modules must export api explicitly."""
    preview_file = tmp_path / "usecaseapi_preview.py"
    preview_file.write_text("value = 1\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SwaggerPreviewError, match="export 'api'"):
        load_preview(None)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_swagger_preview.py -q
```

Expected: import failure because `usecaseapi.swagger` does not exist.

- [ ] **Step 3: Implement discovery and preview loading**

Create `src/usecaseapi/swagger.py`:

```python
"""Development-only Swagger preview support."""

from __future__ import annotations

import importlib
import importlib.util
import sys

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .api import UseCaseAPI
from .errors import UseCaseAPIError

PREVIEW_MODULE_CANDIDATES = (
    Path("usecaseapi_preview.py"),
    Path("preview.py"),
    Path("composition.py"),
    Path("src/composition.py"),
)


class SwaggerPreviewError(UseCaseAPIError):
    """Raised when the development Swagger preview cannot be started."""


@dataclass(frozen=True, slots=True)
class PreviewConfig:
    """Loaded preview configuration."""

    api: UseCaseAPI[Any]
    create_context: Callable[..., Any] | None
    module: ModuleType


def discover_preview_module(*, cwd: Path | None = None) -> Path:
    """Return the first preview module path found by convention."""
    root = cwd or Path.cwd()
    for candidate in PREVIEW_MODULE_CANDIDATES:
        path = root / candidate
        if path.is_file():
            return path
    names = ", ".join(str(candidate) for candidate in PREVIEW_MODULE_CANDIDATES)
    raise SwaggerPreviewError(f"no preview module found; expected one of: {names}")


def load_preview(preview: str | None) -> PreviewConfig:
    """Load a preview module and return its UseCaseAPI configuration."""
    module = import_preview_module(preview)
    api = getattr(module, "api", None)
    if not isinstance(api, UseCaseAPI):
        raise SwaggerPreviewError("preview module must export 'api' as a UseCaseAPI instance")
    create_context = getattr(module, "create_context", None)
    if create_context is not None and not callable(create_context):
        raise SwaggerPreviewError("preview module 'create_context' must be callable")
    return PreviewConfig(api=api, create_context=create_context, module=module)


def import_preview_module(preview: str | None) -> ModuleType:
    """Import an explicit preview target or the convention-discovered preview file."""
    if preview is None:
        return import_preview_file(discover_preview_module())
    path = Path(preview)
    if path.suffix == ".py" or path.exists():
        if not path.is_file():
            raise SwaggerPreviewError(f"preview file does not exist: {preview}")
        return import_preview_file(path)
    return importlib.import_module(preview)


def import_preview_file(path: Path) -> ModuleType:
    """Import a preview module from a Python file path."""
    resolved = path.resolve()
    module_name = "_usecaseapi_preview_" + resolved.stem
    parent = str(resolved.parent)
    added_parent = parent not in sys.path
    if added_parent:
        sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(module_name, resolved)
        if spec is None or spec.loader is None:
            raise SwaggerPreviewError(f"cannot import preview file: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if added_parent:
            sys.path.remove(parent)
```

- [ ] **Step 4: Run discovery tests**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_discovers_usecaseapi_preview_module tests/test_swagger_preview.py::test_load_preview_requires_api_export -q
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/usecaseapi/swagger.py tests/test_swagger_preview.py
git commit -m "feat: discover swagger preview modules"
```

## Task 3: Create FastAPI Preview App

**Files:**
- Modify: `src/usecaseapi/swagger.py`
- Modify: `tests/test_swagger_preview.py`

- [ ] **Step 1: Write failing app tests**

Append to `tests/test_swagger_preview.py`:

```python
def make_bound_api() -> UseCaseAPI[None]:
    """Create a preview API with one bound usecase."""
    api = UseCaseAPI[None]()
    api.bind(PREVIEW_USECASE, lambda caller: PreviewImpl())
    return api


def test_create_swagger_app_calls_bound_usecase() -> None:
    """The preview app exposes a bound usecase as a POST endpoint."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    client = TestClient(create_swagger_app(api=make_bound_api(), create_context=None))

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 4})

    assert response.status_code == 200
    assert response.json() == {"value": 5}


def test_swagger_docs_include_usecase_path() -> None:
    """FastAPI OpenAPI output includes the canonical UseCaseAPI route path."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    client = TestClient(create_swagger_app(api=make_bound_api(), create_context=None))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/_usecases/preview.run/v1/call" in response.json()["paths"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_create_swagger_app_calls_bound_usecase tests/test_swagger_preview.py::test_swagger_docs_include_usecase_path -q
```

Expected: failure because `create_swagger_app` is not implemented.

- [ ] **Step 3: Implement FastAPI app creation**

Add to `src/usecaseapi/swagger.py`:

```python
import inspect

from collections.abc import Awaitable

from .contracts import UseCaseRef


def create_swagger_app(
    *,
    api: UseCaseAPI[Any],
    create_context: Callable[..., Any] | None,
) -> Any:
    """Create the development FastAPI preview app."""
    try:
        from fastapi import FastAPI, Request
    except ImportError as exc:
        raise SwaggerPreviewError(
            "FastAPI preview support is not installed. Install it with: uv sync --extra swagger"
        ) from exc

    app = FastAPI(
        title="UseCaseAPI Swagger Preview",
        version="0.1.0",
        description="Development-only preview server for bound UseCaseAPI usecases.",
    )

    for binding in api.bindings:
        ref = binding.ref
        path = preview_route_path(ref)
        endpoint = make_usecase_endpoint(api=api, ref=ref, create_context=create_context)
        app.post(
            path,
            name=ref.contract.name,
            operation_id=preview_operation_id(ref),
            response_model=ref.contract.output,
        )(endpoint)

    return app


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
    parameters = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if len(parameters) == 0:
        value = create_context()
    elif len(parameters) == 1:
        value = create_context(request)
    else:
        raise SwaggerPreviewError("create_context must accept zero arguments or one request argument")
    if inspect.isawaitable(value):
        return await value
    return value
```

- [ ] **Step 4: Run app tests**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_create_swagger_app_calls_bound_usecase tests/test_swagger_preview.py::test_swagger_docs_include_usecase_path -q
```

Expected: both tests pass.

- [ ] **Step 5: Add missing dependency error test**

Append to `tests/test_swagger_preview.py`:

```python
def test_create_swagger_app_reports_missing_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing preview dependencies produce an explicit install error."""
    import builtins

    from usecaseapi.swagger import create_swagger_app

    original_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "fastapi":
            raise ImportError("blocked fastapi")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(SwaggerPreviewError, match="uv sync --extra swagger"):
        create_swagger_app(api=make_bound_api(), create_context=None)
```

- [ ] **Step 6: Run missing dependency test**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_create_swagger_app_reports_missing_fastapi -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/usecaseapi/swagger.py tests/test_swagger_preview.py
git commit -m "feat: create swagger preview app"
```

## Task 4: Add Request-Aware Context

**Files:**
- Modify: `tests/test_swagger_preview.py`
- Modify: `src/usecaseapi/swagger.py` if Task 3 implementation needs adjustment

- [ ] **Step 1: Write request-aware context test**

Append to `tests/test_swagger_preview.py`:

```python
class MultiplierContext(Model):
    multiplier: int


class ContextImpl:
    def __init__(self, multiplier: int) -> None:
        self.multiplier = multiplier

    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        return PreviewOutput(value=input.value * self.multiplier)


def test_request_headers_can_drive_preview_context() -> None:
    """Preview context factories can inspect the incoming FastAPI request."""
    from fastapi import Request
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    api = UseCaseAPI[MultiplierContext]()
    api.bind(PREVIEW_USECASE, lambda caller: ContextImpl(caller.context.multiplier))

    async def create_context(request: Request) -> MultiplierContext:
        return MultiplierContext(multiplier=int(request.headers["x-multiplier"]))

    client = TestClient(create_swagger_app(api=api, create_context=create_context))

    response = client.post(
        "/_usecases/preview.run/v1/call",
        headers={"x-multiplier": "4"},
        json={"value": 3},
    )

    assert response.status_code == 200
    assert response.json() == {"value": 12}
```

- [ ] **Step 2: Run test**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_request_headers_can_drive_preview_context -q
```

Expected: pass. If it fails because request injection is not recognized, update `make_usecase_endpoint()` signature so FastAPI treats `request` as `fastapi.Request`.

- [ ] **Step 3: Add invalid context factory test**

Append:

```python
def test_context_factory_rejects_unsupported_signature() -> None:
    """Context factories must be either zero-argument or request-aware."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    def create_context(first: object, second: object) -> None:
        return None

    client = TestClient(create_swagger_app(api=make_bound_api(), create_context=create_context))

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 1})

    assert response.status_code == 500
    assert "create_context must accept zero arguments or one request argument" in response.text
```

- [ ] **Step 4: Run context tests**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_request_headers_can_drive_preview_context tests/test_swagger_preview.py::test_context_factory_rejects_unsupported_signature -q
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/usecaseapi/swagger.py tests/test_swagger_preview.py
git commit -m "feat: support request-aware preview context"
```

## Task 5: Add Domain Error Envelope Serialization

**Files:**
- Modify: `src/usecaseapi/swagger.py`
- Modify: `tests/test_swagger_preview.py`

- [ ] **Step 1: Write failing domain error test**

Append:

```python
from typing import ClassVar

from usecaseapi import UseCaseError


class PreviewRejected(UseCaseError):
    code: ClassVar[str] = "preview.rejected"

    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class RejectingImpl:
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        raise PreviewRejected(reason="not allowed")


def test_domain_errors_are_returned_as_envelopes() -> None:
    """Declared UseCaseError instances become preview response envelopes."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    api = UseCaseAPI[None]()
    ref = define_usecase(
        PreviewUseCase,
        Contract(
            name="preview.reject",
            version=1,
            input=PreviewInput,
            output=PreviewOutput,
            raises=(PreviewRejected,),
            known_errors=(PreviewRejected,),
        ),
    )
    api.bind(ref, lambda caller: RejectingImpl())
    client = TestClient(create_swagger_app(api=api, create_context=None))

    response = client.post("/_usecases/preview.reject/v1/call", json={"value": 1})

    assert response.status_code == 400
    assert response.json() == {
        "code": "preview.rejected",
        "error": "PreviewRejected",
        "message": "not allowed",
        "payload": {"reason": "not allowed"},
    }
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_domain_errors_are_returned_as_envelopes -q
```

Expected: failure because no exception handler exists.

- [ ] **Step 3: Implement error handler**

Add to `create_swagger_app()` after app creation:

```python
    register_domain_error_handler(app)
```

Add helpers in `src/usecaseapi/swagger.py`:

```python
def register_domain_error_handler(app: Any) -> None:
    """Register preview serialization for UseCaseAPI domain errors."""
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse

    from .errors import UseCaseError

    @app.exception_handler(UseCaseError)
    async def handle_usecase_error(_request: Any, exc: UseCaseError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=jsonable_encoder(domain_error_envelope(exc)),
        )


def domain_error_envelope(error: Any) -> dict[str, Any]:
    """Serialize a UseCaseError for the development preview."""
    return {
        "code": error.code,
        "error": type(error).__name__,
        "message": str(error),
        "payload": dict(error.details),
    }
```

- [ ] **Step 4: Run error test**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_domain_errors_are_returned_as_envelopes -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/usecaseapi/swagger.py tests/test_swagger_preview.py
git commit -m "feat: serialize preview domain errors"
```

## Task 6: Add CLI Command

**Files:**
- Modify: `src/usecaseapi/cli.py`
- Modify: `tests/test_swagger_preview.py`

- [ ] **Step 1: Write failing CLI tests**

Append:

```python
def test_swagger_cli_starts_preview_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI loads the convention preview module and starts Uvicorn."""
    from usecaseapi.cli import main

    preview_file = tmp_path / "usecaseapi_preview.py"
    preview_file.write_text(
        "from tests.test_swagger_preview import make_bound_api\n"
        "api = make_bound_api()\n",
    )
    monkeypatch.chdir(tmp_path)

    called: dict[str, object] = {}

    def fake_serve_swagger_preview(*, preview: str | None, host: str, port: int) -> None:
        called["preview"] = preview
        called["host"] = host
        called["port"] = port

    monkeypatch.setattr(
        "usecaseapi.swagger.serve_swagger_preview",
        fake_serve_swagger_preview,
    )

    assert main(["swagger"]) == 0
    assert called == {"preview": None, "host": "127.0.0.1", "port": 8000}
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_swagger_cli_starts_preview_server -q
```

Expected: failure because `swagger` command does not exist.

- [ ] **Step 3: Implement CLI command**

Add to `src/usecaseapi/cli.py` imports:

```python
from .errors import UseCaseAPIError
```

Add command near other top-level commands:

```python
@app.command()
def swagger(
    preview: Annotated[
        str | None,
        typer.Option("--preview", help="Preview module name or Python file path"),
    ] = None,
    host: Annotated[str, typer.Option(help="Host for the local preview server")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port for the local preview server")] = 8000,
) -> None:
    """Run a development-only Swagger preview for bound usecases."""
    try:
        from .swagger import serve_swagger_preview

        serve_swagger_preview(preview=preview, host=host, port=port)
    except UseCaseAPIError as exc:
        raise typer.BadParameter(str(exc)) from exc
```

- [ ] **Step 4: Implement server function**

Add to `src/usecaseapi/swagger.py`:

```python
def serve_swagger_preview(*, preview: str | None, host: str, port: int) -> None:
    """Start the blocking Uvicorn server for the preview app."""
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
```

- [ ] **Step 5: Run CLI test**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_swagger_cli_starts_preview_server -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/usecaseapi/cli.py src/usecaseapi/swagger.py tests/test_swagger_preview.py
git commit -m "feat: add swagger preview CLI"
```

## Task 7: Add Basic Example Preview Module

**Files:**
- Create: `examples/basic/usecaseapi_preview.py`
- Modify: `examples/basic/README.md`
- Test: `tests/test_full_service_validation.py` or `tests/test_swagger_preview.py`

- [ ] **Step 1: Add preview file test**

Append to `tests/test_swagger_preview.py`:

```python
def test_basic_example_preview_module_runs_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    """The basic example preview module can execute through the preview app."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app, load_preview

    monkeypatch.chdir("examples/basic")
    monkeypatch.syspath_prepend("src")
    config = load_preview(None)
    client = TestClient(create_swagger_app(api=config.api, create_context=config.create_context))

    accepted = client.post(
        "/_usecases/commerce.place_order/v1/call",
        json={"user_id": "user_123", "item": {"sku_id": "sku_456", "quantity": 2}},
    )
    shortage = client.post(
        "/_usecases/commerce.place_order/v1/call",
        headers={"x-usecaseapi-scenario": "empty"},
        json={"user_id": "user_123", "item": {"sku_id": "sku_456", "quantity": 2}},
    )

    assert accepted.status_code == 200
    assert accepted.json() == {"order_id": "ord_123", "status": "accepted"}
    assert shortage.status_code == 400
    assert shortage.json()["code"] == "commerce.place_order.inventory_shortage"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_basic_example_preview_module_runs_scenarios -q
```

Expected: failure because `examples/basic/usecaseapi_preview.py` does not exist.

- [ ] **Step 3: Create example preview module**

Create `examples/basic/usecaseapi_preview.py`:

```python
"""Swagger preview composition for the basic example."""

from __future__ import annotations

from fastapi import Request

from commerce.usecases.check_availability.v1.check_availability_usecase import InventoryStore
from composition import AppContext, usecases

api = usecases


async def create_context(request: Request) -> AppContext:
    """Create request-specific preview context for Swagger Try it out."""
    scenario = request.headers.get("x-usecaseapi-scenario", "default")
    stock_by_scenario = {
        "default": {"sku_456": 10, "sku_sold_out": 0},
        "empty": {"sku_456": 0, "sku_sold_out": 0},
        "rich": {"sku_456": 100, "sku_sold_out": 5},
    }
    if scenario not in stock_by_scenario:
        scenario = "default"
    return AppContext(store=InventoryStore(stock_by_scenario[scenario]))
```

- [ ] **Step 4: Update example README**

Add to `examples/basic/README.md`:

````markdown
## Swagger Preview

Run the development preview from this directory:

```bash
uv run usecaseapi swagger
```

Open `http://127.0.0.1:8000/docs` and use Swagger UI `Try it out`.

The preview module reads `x-usecaseapi-scenario` to switch inventory fixtures:

- `default`: `sku_456` has stock.
- `empty`: `sku_456` has no stock.
- `rich`: all example SKUs have stock.
````

- [ ] **Step 5: Run example preview test**

Run:

```bash
uv run pytest tests/test_swagger_preview.py::test_basic_example_preview_module_runs_scenarios -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add examples/basic/usecaseapi_preview.py examples/basic/README.md tests/test_swagger_preview.py
git commit -m "test: add basic swagger preview example"
```

## Task 8: Add Public Docs

**Files:**
- Create: `docs/swagger-preview.md`
- Modify: `README.md`

- [ ] **Step 1: Create docs page**

Create `docs/swagger-preview.md`:

````markdown
# Swagger Preview

UseCaseAPI can run a development-only Swagger preview for bound usecases.

```bash
uv run usecaseapi swagger
```

The command discovers `usecaseapi_preview.py`, loads its `api` export, creates one local `POST`
route per bound usecase, and serves FastAPI Swagger UI at `http://127.0.0.1:8000/docs`.

This is not a production HTTP adapter. It is for quick local verification of usecase inputs,
outputs, dependency wiring, and domain errors.

## Preview Module

```python
from fastapi import Request

from composition import AppContext, usecases

api = usecases

async def create_context(request: Request) -> AppContext:
    scenario = request.headers.get("x-usecaseapi-scenario", "default")
    stock = {"sku_456": 10} if scenario == "default" else {"sku_456": 0}
    return AppContext(store=InventoryStore(stock))
```

The request body remains the usecase input model. Use headers or query parameters inside
`create_context(request)` to switch preview scenarios.

## Discovery

By default, `usecaseapi swagger` searches for:

1. `usecaseapi_preview.py`
2. `preview.py`
3. `composition.py`
4. `src/composition.py`

You can specify a module or file explicitly:

```bash
uv run usecaseapi swagger --preview usecaseapi_preview
uv run usecaseapi swagger --preview path/to/usecaseapi_preview.py
```
````

- [ ] **Step 2: Link from README**

Add one bullet in `README.md` feature/CLI section:

```markdown
- Run `usecaseapi swagger` for a development-only Swagger UI that can execute bound usecases.
```

- [ ] **Step 3: Run docs-related checks**

Run:

```bash
rg -n "usecaseapi swagger|development-only|usecaseapi_preview" docs/swagger-preview.md README.md
```

Expected: matches are printed from both docs files.

- [ ] **Step 4: Commit**

```bash
git add docs/swagger-preview.md README.md
git commit -m "docs: document swagger preview"
```

## Task 9: Full Verification And Versioning

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Bump version**

Because this adds a shipped feature, bump patch version in `pyproject.toml`:

```toml
version = "2.0.2"
```

Update the editable package version in `uv.lock` to the same value via:

```bash
uv lock
```

If `uv lock` changes `exclude-newer`, restore the prior `exclude-newer` value unless a dependency refresh intentionally requires changing it.

- [ ] **Step 2: Run focused preview tests**

Run:

```bash
uv run pytest tests/test_swagger_preview.py -q
```

Expected:

```text
tests/test_swagger_preview.py passes
```

- [ ] **Step 3: Run basic example preview check**

Run:

```bash
cd examples/basic
PYTHONPATH=src uv run python - <<'PY'
from fastapi.testclient import TestClient
from usecaseapi.swagger import create_swagger_app, load_preview

config = load_preview(None)
client = TestClient(create_swagger_app(api=config.api, create_context=config.create_context))
response = client.post(
    "/_usecases/commerce.place_order/v1/call",
    json={"user_id": "user_123", "item": {"sku_id": "sku_456", "quantity": 2}},
)
print(response.status_code, response.json())
PY
```

Expected:

```text
200 {'order_id': 'ord_123', 'status': 'accepted'}
```

- [ ] **Step 4: Run full repository checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run coverage run -m pytest
uv run coverage report -m
uv build
uv run twine check dist/*
```

Expected:

- Ruff passes.
- Format check passes.
- Mypy reports no issues.
- Pytest passes.
- Coverage remains 100% or the PR coverage check remains non-decreasing.
- Build and twine check pass.

- [ ] **Step 5: Commit version and verification updates**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: bump version for swagger preview"
```

## Task 10: Manual Browser Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Start preview server from the basic example**

Run:

```bash
cd examples/basic
PYTHONPATH=src uv run usecaseapi swagger
```

Expected terminal output:

```text
UseCaseAPI Swagger preview running at:
  http://127.0.0.1:8000/docs
```

- [ ] **Step 2: Open Swagger UI**

Open:

```text
http://127.0.0.1:8000/docs
```

Expected:

- Swagger UI loads.
- `POST /_usecases/commerce.place_order/v1/call` is visible.
- Request body schema matches `PlaceOrderUseCaseInput`.

- [ ] **Step 3: Execute success case**

Use `Try it out` with:

```json
{
  "user_id": "user_123",
  "item": {
    "sku_id": "sku_456",
    "quantity": 2
  }
}
```

Expected response:

```json
{
  "order_id": "ord_123",
  "status": "accepted"
}
```

- [ ] **Step 4: Execute domain error case**

Add header:

```text
x-usecaseapi-scenario: empty
```

Use the same body:

```json
{
  "user_id": "user_123",
  "item": {
    "sku_id": "sku_456",
    "quantity": 2
  }
}
```

Expected response status: `400`

Expected response body includes:

```json
{
  "code": "commerce.place_order.inventory_shortage",
  "error": "InventoryShortage"
}
```

- [ ] **Step 5: Stop the server and commit no files**

Stop the process with `Ctrl-C`.

Run:

```bash
git status --short
```

Expected: no generated files from manual verification.

## Self-Review

- Spec coverage: Task 2 covers preview discovery; Tasks 3-6 cover FastAPI app creation, request parsing, UseCaseAPI invocation, request-aware context, domain error envelopes, and CLI startup; Task 7 covers the basic example; Task 8 covers public docs; Tasks 9-10 cover automated and manual verification.
- Placeholder scan: the plan contains no placeholder tokens, incomplete implementation steps, or unspecified error handling. Ellipsis appears only in Protocol method bodies where it is valid Python.
- Type consistency: `PreviewConfig`, `SwaggerPreviewError`, `create_swagger_app`, `serve_swagger_preview`, and `create_context` signatures are introduced before later tasks reference them.
