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


def import_preview_module(preview: str | None) -> ModuleType:
    """Import a preview module from discovery, a file path, or a module name."""
    if preview is None:
        return import_preview_file(discover_preview_module())

    path = Path(preview)
    if path.suffix == ".py" or path.exists():
        if not path.is_file():
            raise SwaggerPreviewError(f"preview path {preview!r} is not a file")
        return import_preview_file(path)

    return importlib.import_module(preview)


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
