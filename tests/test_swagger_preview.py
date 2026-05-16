"""Swagger preview module discovery tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

import pytest

from usecaseapi import Contract, Model, UseCase, UseCaseAPI, UseCaseRef, define_usecase
from usecaseapi.swagger import SwaggerPreviewError, discover_preview_module, load_preview


class PreviewInput(Model):
    value: int


class PreviewOutput(Model):
    value: int


class PreviewUseCase(UseCase[PreviewInput, PreviewOutput], Protocol):
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput: ...


PREVIEW_USECASE: UseCaseRef[PreviewInput, PreviewOutput] = define_usecase(
    PreviewUseCase,
    Contract(name="preview.run", version=1, input=PreviewInput, output=PreviewOutput),
)


class PreviewImpl:
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        return PreviewOutput(value=input.value + 1)


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
