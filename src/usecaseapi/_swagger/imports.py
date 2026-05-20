"""Swagger preview import and exported API loading."""
# mypy: ignore-errors

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import inspect
import sys

from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

from usecaseapi.api import UseCaseAPI

from .discovery import (
    API_EXPORT_NAMES,
    FACTORY_EXPORT_NAMES,
    SwaggerPreviewError,
    discover_preview_target,
    project_import_roots,
)


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
    with preview_runtime_import_roots(module):
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


@contextlib.contextmanager
def preview_runtime_import_roots(module: ModuleType) -> Iterator[None]:
    """Keep project import roots available while preview factories execute."""
    roots = [str(path.resolve()) for path in project_import_roots(Path.cwd())]
    module_file = getattr(module, "__file__", None)
    if module_file is not None:
        roots.insert(0, str(Path(module_file).resolve().parent))
    added_roots = [
        root
        for index, root in enumerate(roots)
        if root not in sys.path and root not in roots[:index]
    ]
    sys.path[:0] = added_roots
    try:
        yield
    finally:
        for root in reversed(added_roots):
            sys.path.remove(root)


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


__all__ = [name for name in globals() if not name.startswith("__")]
