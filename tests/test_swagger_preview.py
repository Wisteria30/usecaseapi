"""Swagger preview module discovery tests."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pytest

from usecaseapi import Contract, Model, UseCase, UseCaseRef, define_usecase
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
