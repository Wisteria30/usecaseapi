"""Swagger preview module discovery tests."""

from __future__ import annotations

import importlib.util
import sys

from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar, Protocol

import pytest

from usecaseapi import (
    Contract,
    Model,
    UseCase,
    UseCaseAPI,
    UseCaseError,
    UseCaseRef,
    define_usecase,
)
from usecaseapi.swagger import SwaggerPreviewError, discover_preview_module, load_preview


class PreviewInput(Model):
    value: int


class PreviewOutput(Model):
    value: int


class MultiplierContext(Model):
    multiplier: int


class PreviewUseCase(UseCase[PreviewInput, PreviewOutput], Protocol):
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput: ...


PREVIEW_USECASE: UseCaseRef[PreviewInput, PreviewOutput] = define_usecase(
    PreviewUseCase,
    Contract(name="preview.run", version=1, input=PreviewInput, output=PreviewOutput),
)


class PreviewImpl:
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        return PreviewOutput(value=input.value + 1)


class PreviewRejected(UseCaseError):
    code: ClassVar[str] = "preview.rejected"

    def __init__(self, *, reason: str) -> None:
        """Create a rejected preview domain error."""
        self.reason = reason
        super().__init__(reason)


class RejectingImpl:
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        raise PreviewRejected(reason="not allowed")


class ContextImpl:
    def __init__(self, multiplier: int) -> None:
        """Create a preview implementation that multiplies input values."""
        self.multiplier = multiplier

    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        return PreviewOutput(value=input.value * self.multiplier)


def make_bound_api() -> UseCaseAPI[None]:
    """Create a preview API with one bound usecase."""
    api = UseCaseAPI[None]()
    api.bind(PREVIEW_USECASE, lambda caller: PreviewImpl())
    return api


def test_discovers_usecaseapi_preview_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default preview module is discovered from the current working directory."""
    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")
    monkeypatch.chdir(tmp_path)

    assert discover_preview_module() == preview_path


def test_discovers_dev_preview_before_root_preview(tmp_path: Path) -> None:
    """Project-local test preview modules take precedence over root preview files."""
    root_preview = tmp_path / "usecaseapi_preview.py"
    tests_preview = tmp_path / "tests" / "usecaseapi_preview.py"
    tests_preview.parent.mkdir()
    root_preview.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")
    tests_preview.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")

    assert discover_preview_module(cwd=tmp_path) == tests_preview


def test_discover_preview_module_reports_supported_names(tmp_path: Path) -> None:
    """Missing preview modules report the supported discovery filenames."""
    with pytest.raises(SwaggerPreviewError) as exc_info:
        discover_preview_module(cwd=tmp_path)

    message = str(exc_info.value)
    assert "could not find preview module" in message
    assert "tests/usecaseapi_preview.py" in message
    assert "usecaseapi_preview.py" in message
    assert "src/composition.py" in message


def test_load_preview_requires_api_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preview modules must export a supported UseCaseAPI instance."""
    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("value = 1\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SwaggerPreviewError, match="export 'api' or 'usecases'"):
        load_preview(None)


def test_load_preview_accepts_usecases_export(tmp_path: Path) -> None:
    """Existing composition modules can expose usecases without a preview-only api alias."""
    preview_path = tmp_path / "composition.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\n\nusecases = UseCaseAPI[None]()\n")

    config = load_preview(str(preview_path))

    assert isinstance(config.api, UseCaseAPI)


def test_load_preview_requires_callable_context_factory(tmp_path: Path) -> None:
    """Preview modules must not export non-callable create_context values."""
    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text(
        "from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\ncreate_context = 1\n"
    )

    with pytest.raises(SwaggerPreviewError, match="create_context"):
        load_preview(str(preview_path))


def test_create_swagger_app_calls_bound_usecase() -> None:
    """The preview app exposes a bound usecase as a POST endpoint."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    client = TestClient(create_swagger_app(api=make_bound_api(), create_context=None))

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 4})

    assert response.status_code == 200
    assert response.json() == {"value": 5}


def test_domain_errors_are_returned_as_envelopes() -> None:
    """Domain errors are serialized as explicit JSON envelopes."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    ref: UseCaseRef[PreviewInput, PreviewOutput] = define_usecase(
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
    api = UseCaseAPI[None]()
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


def test_swagger_docs_include_usecase_path() -> None:
    """FastAPI OpenAPI output includes the canonical UseCaseAPI route path."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    client = TestClient(create_swagger_app(api=make_bound_api(), create_context=None))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/_usecases/preview.run/v1/call" in response.json()["paths"]


def test_swagger_docs_include_preview_scenario_header_parameter() -> None:
    """FastAPI OpenAPI output exposes the preview scenario header."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    client = TestClient(create_swagger_app(api=make_bound_api(), create_context=None))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/_usecases/preview.run/v1/call"]["post"]
    scenario_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "x-usecaseapi-scenario" and parameter["in"] == "header"
    )
    scenario_schema = scenario_parameter["schema"]
    request_body_schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert scenario_parameter["required"] is False
    assert scenario_schema.get("type") == "string" or {"type": "string"} in scenario_schema.get(
        "anyOf", []
    )
    assert request_body_schema == {"$ref": "#/components/schemas/PreviewInput"}


def test_create_swagger_app_supports_keyword_only_request_context() -> None:
    """Keyword-only request factories can create the per-request context."""
    from fastapi import Request
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    class ContextPreviewImpl:
        def __init__(self, increment: int) -> None:
            self.increment = increment

        async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
            return PreviewOutput(value=input.value + self.increment)

    def create_context(*, request: Request) -> int:
        assert request.url.path == "/_usecases/preview.run/v1/call"
        return 6

    api = UseCaseAPI[int]()
    api.bind(PREVIEW_USECASE, lambda caller: ContextPreviewImpl(caller.context))
    client = TestClient(create_swagger_app(api=api, create_context=create_context))

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 4})

    assert response.status_code == 200
    assert response.json() == {"value": 10}


def test_create_swagger_app_supports_zero_argument_context_factory() -> None:
    """Zero-argument context factories are evaluated once per request."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    api = UseCaseAPI[MultiplierContext]()
    api.bind(PREVIEW_USECASE, lambda caller: ContextImpl(caller.context.multiplier))

    def create_context() -> MultiplierContext:
        return MultiplierContext(multiplier=5)

    client = TestClient(create_swagger_app(api=api, create_context=create_context))

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 3})

    assert response.status_code == 200
    assert response.json() == {"value": 15}


def test_request_headers_can_drive_preview_context() -> None:
    """Preview context factories can read the current HTTP request."""
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
        json={"value": 3},
        headers={"x-multiplier": "4"},
    )

    assert response.status_code == 200
    assert response.json() == {"value": 12}


def test_basic_example_preview_module_runs_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    """The basic example preview module exposes inventory scenarios."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    monkeypatch.chdir("examples/basic")

    config = load_preview(None)
    client = TestClient(create_swagger_app(api=config.api, create_context=config.create_context))
    payload = {"user_id": "user_123", "item": {"sku_id": "sku_456", "quantity": 2}}

    accepted = client.post("/_usecases/commerce.place_order/v1/call", json=payload)
    shortage = client.post(
        "/_usecases/commerce.place_order/v1/call",
        json=payload,
        headers={"x-usecaseapi-scenario": "empty"},
    )

    assert accepted.status_code == 200
    assert accepted.json() == {"order_id": "ord_123", "status": "accepted"}
    assert shortage.status_code == 400
    assert shortage.json()["code"] == "commerce.place_order.inventory_shortage"


def test_basic_example_preview_module_rejects_unknown_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The basic preview reports unknown inventory scenarios explicitly."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    monkeypatch.chdir("examples/basic")

    config = load_preview(None)
    client = TestClient(
        create_swagger_app(api=config.api, create_context=config.create_context),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/_usecases/commerce.place_order/v1/call",
        json={"user_id": "user_123", "item": {"sku_id": "sku_456", "quantity": 2}},
        headers={"x-usecaseapi-scenario": "unknown"},
    )

    assert response.status_code == 500
    assert "unknown x-usecaseapi-scenario value 'unknown'" in response.text
    assert "default" in response.text
    assert "empty" in response.text
    assert "rich" in response.text


def test_context_factory_rejects_unsupported_signature() -> None:
    """Preview context factories must have a supported signature."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    def create_context(first: object, second: object) -> None:
        raise AssertionError("unsupported context factory should not be called")

    client = TestClient(
        create_swagger_app(api=make_bound_api(), create_context=create_context),
        raise_server_exceptions=False,
    )

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 1})

    assert response.status_code == 500
    assert "create_context must accept zero arguments or one request argument" in response.text


def test_create_swagger_app_reports_missing_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing preview dependencies produce an explicit install error."""
    import builtins

    from usecaseapi.swagger import create_swagger_app

    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_: Mapping[str, object] | None = None,
        locals_: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "fastapi":
            raise ImportError("blocked fastapi")
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(SwaggerPreviewError, match="uv sync --extra swagger"):
        create_swagger_app(api=make_bound_api(), create_context=None)


def test_serve_swagger_preview_reports_missing_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing server dependencies produce an explicit install error."""
    import builtins

    from usecaseapi.swagger import serve_swagger_preview

    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_: Mapping[str, object] | None = None,
        locals_: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "uvicorn":
            raise ImportError("blocked uvicorn")
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(SwaggerPreviewError, match="uv sync --extra swagger"):
        serve_swagger_preview(preview=None, host="127.0.0.1", port=8000)


def test_serve_swagger_preview_loads_app_and_starts_uvicorn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The server wrapper loads preview config and delegates to uvicorn."""
    from usecaseapi.swagger import serve_swagger_preview

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")
    calls: list[dict[str, object]] = []

    def run(app: object, *, host: str, port: int) -> None:
        calls.append({"app": app, "host": host, "port": port})

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))

    serve_swagger_preview(preview=str(preview_path), host="127.0.0.1", port=8765)

    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8765
    assert "http://127.0.0.1:8765/docs" in capsys.readouterr().out


def test_serve_swagger_preview_increments_unavailable_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The server wrapper opens the next available port when the requested one is busy."""
    from usecaseapi.swagger import serve_swagger_preview

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")
    calls: list[dict[str, object]] = []

    def run(app: object, *, host: str, port: int) -> None:
        calls.append({"app": app, "host": host, "port": port})

    def is_port_available(*, host: str, port: int) -> bool:
        return port == 8002

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))
    monkeypatch.setattr("usecaseapi.swagger.is_port_available", is_port_available)

    serve_swagger_preview(preview=str(preview_path), host="127.0.0.1", port=8000)

    assert len(calls) == 1
    assert calls[0]["port"] == 8002
    output = capsys.readouterr().out
    assert "requested port 8000 is unavailable; using 8002" in output
    assert "http://127.0.0.1:8002/docs" in output


def test_select_available_port_reports_exhausted_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Port selection reports an explicit error when no port can be bound."""
    from usecaseapi.swagger import select_available_port

    monkeypatch.setattr("usecaseapi.swagger.is_port_available", lambda *, host, port: False)

    with pytest.raises(SwaggerPreviewError, match="at or above 65535"):
        select_available_port(host="127.0.0.1", preferred_port=65535)


def test_is_port_available_detects_bound_port() -> None:
    """A port already bound by another socket is unavailable."""
    import socket

    from usecaseapi.swagger import is_port_available

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        occupied_port = sock.getsockname()[1]

        assert not is_port_available(host="127.0.0.1", port=occupied_port)


def test_swagger_cli_starts_preview_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The swagger CLI command starts the local preview server with defaults."""
    from usecaseapi.cli import main

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text(
        "from tests.test_swagger_preview import make_bound_api\napi = make_bound_api()\n"
    )
    monkeypatch.chdir(tmp_path)
    called: dict[str, object] = {}

    def fake_serve_swagger_preview(*, preview: str | None, host: str, port: int) -> None:
        called["preview"] = preview
        called["host"] = host
        called["port"] = port

    monkeypatch.setattr("usecaseapi.swagger.serve_swagger_preview", fake_serve_swagger_preview)

    assert main(["swagger"]) == 0
    assert called == {"preview": None, "host": "127.0.0.1", "port": 8000}


def test_swagger_cli_reports_missing_preview_module() -> None:
    """A missing preview module is reported through the CLI error path."""
    from usecaseapi.cli import main

    assert main(["swagger", "--preview", "definitely_missing_preview_module_123"]) == 2


def test_swagger_cli_propagates_unrelated_usecaseapi_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only Swagger preview errors are converted into CLI argument errors."""
    from usecaseapi.cli import main
    from usecaseapi.errors import UseCaseAPIError

    class UnrelatedUseCaseAPIError(UseCaseAPIError):
        """UseCaseAPI error outside the Swagger preview boundary."""

    def fake_serve_swagger_preview(*, preview: str | None, host: str, port: int) -> None:
        raise UnrelatedUseCaseAPIError("internal failure")

    monkeypatch.setattr("usecaseapi.swagger.serve_swagger_preview", fake_serve_swagger_preview)

    with pytest.raises(UnrelatedUseCaseAPIError):
        main(["swagger"])


def test_import_preview_module_rejects_directory_path(tmp_path: Path) -> None:
    """Preview paths must point to Python files."""
    from usecaseapi.swagger import import_preview_module

    with pytest.raises(SwaggerPreviewError, match="is not a file"):
        import_preview_module(str(tmp_path))


def test_import_preview_module_preserves_dependency_import_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Import errors raised by preview module dependencies are not rewritten."""
    from usecaseapi.swagger import import_preview_module

    preview_path = tmp_path / "broken_preview.py"
    preview_path.write_text("import missing_preview_dependency_123\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ModuleNotFoundError, match="missing_preview_dependency_123"):
        import_preview_module("broken_preview")


def test_import_preview_file_reports_missing_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview file imports fail explicitly when importlib cannot create a loader."""
    from usecaseapi.swagger import import_preview_file

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\napi = UseCaseAPI[None]()\n")
    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *args: None)

    with pytest.raises(SwaggerPreviewError, match="could not create import loader"):
        import_preview_file(preview_path)


def test_import_preview_file_removes_failed_module_from_cache(tmp_path: Path) -> None:
    """Failed preview file execution does not leave its temporary module cached."""
    from usecaseapi.swagger import import_preview_file

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("raise RuntimeError('preview boom')\n")
    cached_before = {
        name for name in sys.modules if name.startswith("_usecaseapi_swagger_preview_")
    }

    with pytest.raises(RuntimeError, match="preview boom"):
        import_preview_file(preview_path)

    cached_after = {name for name in sys.modules if name.startswith("_usecaseapi_swagger_preview_")}
    assert cached_after == cached_before
