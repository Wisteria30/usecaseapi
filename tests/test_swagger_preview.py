"""Swagger preview module discovery tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
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


def test_load_preview_requires_api_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preview modules must export a UseCaseAPI instance named api."""
    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("value = 1\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SwaggerPreviewError, match="export 'api'"):
        load_preview(None)


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
