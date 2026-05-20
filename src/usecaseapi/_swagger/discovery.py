"""Swagger preview target discovery."""

from __future__ import annotations

import ast

from dataclasses import dataclass
from pathlib import Path

from usecaseapi.errors import UseCaseAPIError
from usecaseapi.swagger_graph import PreviewGraph

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
    """Loaded Swagger preview graph configuration."""

    graphs: tuple[PreviewGraph, ...]


@dataclass(frozen=True, slots=True)
class PreviewTargetCandidate:
    """Importable preview target discovered from project composition code."""

    target: str
    path: Path
    score: tuple[int, int]


def discover_preview_module(*, cwd: Path | None = None) -> Path:
    """Discover the first supported preview module path under a working directory."""
    path = discover_preview_module_or_none(cwd=cwd)
    if path is not None:
        return path
    expected = ", ".join(str(candidate) for candidate in PREVIEW_MODULE_CANDIDATES)
    raise SwaggerPreviewError(f"could not find preview module; expected one of: {expected}")


def discover_preview_module_or_none(*, cwd: Path | None = None) -> Path | None:
    """Return the first supported preview module path or None when no file exists."""
    root = Path.cwd() if cwd is None else cwd
    for candidate in PREVIEW_MODULE_CANDIDATES:
        path = root / candidate
        if path.is_file():
            return path
    return None


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


__all__ = [name for name in globals() if not name.startswith("__")]
