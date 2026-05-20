"""General Manifest helper functions."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

import inspect
import keyword
import sys

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from usecaseapi.contracts import UseCaseRef
from usecaseapi.errors import UseCaseError

from .common import *
from .common import _EMPTY_SCHEMA_KEYS


def default_contract_file(usecase: Mapping[str, Any], *, contracts_root: str) -> str:
    """Return the default generated contract file path."""
    name = required_string(usecase, "name")
    version = required_int(usecase, "version")
    parts = name.split(".")
    return str(Path(contracts_root) / Path(*parts[:-1]) / parts[-1] / f"v{version}.py")


def default_implementation_file(usecase: Mapping[str, Any], *, implementations_root: str) -> str:
    """Return the default generated implementation file path."""
    name = required_string(usecase, "name")
    parts = name.split(".")
    return str(Path(implementations_root) / Path(*parts[:-1]) / f"{parts[-1]}.py")


def default_manifest_test_file(usecase: Mapping[str, Any], *, tests_root: str) -> str:
    """Return the default generated pytest file path for a Manifest usecase."""
    name = required_string(usecase, "name")
    version = required_int(usecase, "version")
    parts = name.split(".")
    return str(
        Path(tests_root) / Path(*parts[:-1]) / parts[-1] / f"v{version}" / f"test_{parts[-1]}.py"
    )


def module_from_python_file(path: Path, *, package: str | None) -> str:
    """Return an import module for a generated Python file."""
    parts = list(path.with_suffix("").parts)
    if package is not None and package in parts:
        parts = parts[parts.index(package) :]
    return ".".join(parts)


def default_implementation_class(name: str) -> str:
    """Return the default v1.1 implementation class name for exported source metadata."""
    return "".join(part.capitalize() for part in name.split(".")[-1].split("_")) + "UseCase"


def default_implementation_path(
    name: str,
    *,
    version: int,
    implementations_root: str,
    package: str | None,
) -> str:
    """Return the default implementation path for exported source metadata."""
    parts = name.split(".")
    if package is not None and parts[0] == package:
        package_name = package
        usecase_parts = parts[1:]
    else:
        package_name = parts[0]
        usecase_parts = parts[1:]
    usecase_name = parts[-1]
    return str(
        Path(implementations_root)
        / package_name
        / "usecases"
        / Path(*usecase_parts)
        / f"v{version}"
        / f"{usecase_name}_usecase.py"
    )


def write_generated_file(path: Path, content: str, *, force: bool, dry_run: bool) -> None:
    """Write a generated file unless dry-run or protected by force."""
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass force=True to overwrite")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def ensure_init_files(directory: Path, *, stop_at: Path) -> None:
    """Create package __init__.py files up to a boundary."""
    current = directory
    stop = stop_at.resolve()
    while True:
        if current.resolve() == stop or current.parent == current:
            break
        init_file = current / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""Generated package."""\n')
        current = current.parent


def source_file(value: Any) -> str | None:
    """Return a source file path for an inspected object when available."""
    try:
        file_name = inspect.getsourcefile(value)
    except TypeError:
        return None
    if file_name is None:
        return None
    path = Path(file_name).resolve()
    try:
        return path.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def trim_to_root(file_path: str, root: str) -> str:
    """Trim a source path so it starts at the configured root."""
    path_parts = Path(file_path).parts
    root_parts = Path(root).parts
    if not root_parts:
        return file_path
    for index in range(0, len(path_parts) - len(root_parts) + 1):
        if path_parts[index : index + len(root_parts)] == root_parts:
            return str(Path(*path_parts[index:]))
    return file_path


def qualname(value: object) -> str:
    """Return a stable module-qualified name when available."""
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        return f"{module}.{qualname}"
    return repr(value)


def find_ref_symbol(ref: UseCaseRef[Any, Any]) -> str | None:
    """Find the symbol name that exports a UseCaseRef."""
    module = sys.modules.get(ref.protocol.__module__)
    if module is None:
        return None
    for name, value in vars(module).items():
        if value is ref and name.isidentifier():
            return name
    return None


def default_ref_symbol(name: str) -> str:
    """Return the default constant name for a contract."""
    return name.split(".")[-1].upper()


def class_name(error_type: type[UseCaseError]) -> str:
    """Return the class name for an error type."""
    return error_type.__name__


def valid_contract_name(name: str) -> bool:
    """Return whether a contract name is valid."""
    parts = name.split(".")
    return len(parts) >= 2 and all(
        valid_python_identifier(part) and part.islower() for part in parts
    )


def valid_key(key: str) -> bool:
    """Return whether a usecase key is valid."""
    if "@v" not in key:
        return False
    name, _, version = key.partition("@v")
    return valid_contract_name(name) and version.isdigit() and int(version) >= 1


def valid_module_path(value: str) -> bool:
    """Return whether a dotted Python module path is valid."""
    return bool(value) and all(valid_python_identifier(part) for part in value.split("."))


def valid_python_identifier(value: str) -> bool:
    """Return whether a value is a Python identifier that can be generated safely."""
    return value.isidentifier() and not keyword.iskeyword(value)


def error_extends(error_name: str, base_name: str, base_by_name: Mapping[str, str]) -> bool:
    """Return whether one error extends another by Manifest metadata."""
    current = error_name
    while current != "UseCaseError":
        if current == base_name:
            return True
        current = base_by_name.get(current, "UseCaseError")
    return base_name == "UseCaseError"


def required_string(mapping: Mapping[str, Any], key: str) -> str:
    """Read a required non-empty string field."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{key} must be a non-empty string")
    return value


def required_int(mapping: Mapping[str, Any], key: str) -> int:
    """Read a required integer field."""
    value = mapping.get(key)
    if not isinstance(value, int):
        raise ManifestError(f"{key} must be an integer")
    return value


def string_or_default(value: object, default: str) -> str:
    """Read a non-empty string or return a default."""
    return value if isinstance(value, str) and value else default


def string_list(value: object) -> list[str]:
    """Read a list of strings, rejecting malformed values."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestError("expected a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ManifestError("expected a list of strings")
        result.append(item)
    return result


def required_mapping(value: object, name: str) -> Mapping[str, Any]:
    """Read a required mapping value."""
    if not isinstance(value, Mapping):
        raise ManifestError(f"{name} must be a mapping")
    return value


def without_none(value: dict[str, Any], *, preserve_empty: bool = False) -> dict[str, Any]:
    """Return a copy without None values, including nested mappings."""
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            nested = without_none(item, preserve_empty=preserve_empty or key == "properties")
            if nested or key == "properties" or key in _EMPTY_SCHEMA_KEYS or preserve_empty:
                result[key] = nested
        elif item is not None:
            result[key] = item
    return result


__all__ = [name for name in globals() if not name.startswith("__")]
