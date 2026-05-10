"""Scaffold versioned usecase contracts, implementations, and tests."""

from __future__ import annotations

import re

from dataclasses import dataclass
from pathlib import Path

_USECASE_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_VERSION_DIR = re.compile(r"^v([1-9][0-9]*)$")


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    """Files planned or created by the scaffold command."""

    files: tuple[Path, ...]
    version: int = 1


@dataclass(frozen=True, slots=True)
class ScaffoldOptions:
    """Options for creating a versioned usecase skeleton.

    ``next=True`` means "copy the latest existing contract version forward and
    create the next available major version".
    """

    name: str
    version: int | None = None
    next: bool = False
    output_root: Path = Path(".")
    tests_root: Path = Path("tests")
    force: bool = False
    dry_run: bool = False


def scaffold_usecase(options: ScaffoldOptions) -> ScaffoldResult:
    """Create contract, implementation, and optional test files for one usecase."""
    _validate_options(options)
    parts = options.name.split(".")
    package_parts = parts[:-1]
    usecase_name = parts[-1]
    version = _resolve_version(
        options,
        package_parts=package_parts,
        usecase_name=usecase_name,
    )

    class_name = _camel(usecase_name)
    constant_name = f"{usecase_name.upper()}_USECASE"
    usecase_class_name = f"{class_name}UseCase"
    input_class_name = f"{usecase_class_name}Input"
    output_class_name = f"{usecase_class_name}Output"

    version_dir = (
        options.output_root / Path(*package_parts) / "usecases" / usecase_name / f"v{version}"
    )
    contract_file = version_dir / f"{usecase_name}_contract.py"
    implementation_file = version_dir / f"{usecase_name}_usecase.py"
    test_file = (
        options.tests_root
        / Path(*package_parts)
        / "usecases"
        / usecase_name
        / f"v{version}"
        / f"test_{usecase_name}.py"
    )

    contract_module = ".".join(
        [
            *package_parts,
            "usecases",
            usecase_name,
            f"v{version}",
            f"{usecase_name}_contract",
        ]
    )
    implementation_module = ".".join(
        [
            *package_parts,
            "usecases",
            usecase_name,
            f"v{version}",
            f"{usecase_name}_usecase",
        ]
    )

    if options.next:
        previous_contract_file = (
            options.output_root
            / Path(*package_parts)
            / "usecases"
            / usecase_name
            / f"v{version - 1}"
            / f"{usecase_name}_contract.py"
        )
        contract_content = _copy_contract_template(
            previous_contract_file,
            source_version=version - 1,
            target_version=version,
        )
    else:
        contract_content = _contract_template(
            name=options.name,
            version=version,
            class_name=class_name,
            input_class_name=input_class_name,
            output_class_name=output_class_name,
            constant_name=constant_name,
        )

    created: list[Path] = []

    _write_file(contract_file, contract_content, force=options.force, dry_run=options.dry_run)
    created.append(contract_file)

    _write_file(
        implementation_file,
        _implementation_template(
            usecase_name=usecase_name,
            class_name=usecase_class_name,
            input_class_name=input_class_name,
            output_class_name=output_class_name,
        ),
        force=options.force,
        dry_run=options.dry_run,
    )
    created.append(implementation_file)

    _write_file(
        test_file,
        _test_template(
            contract_module=contract_module,
            implementation_module=implementation_module,
            usecase_name=usecase_name,
            class_name=class_name,
            usecase_class_name=usecase_class_name,
            constant_name=constant_name,
            name=options.name,
            version=version,
        ),
        force=options.force,
        dry_run=options.dry_run,
    )
    created.append(test_file)

    if not options.dry_run:
        _ensure_init_files(
            contract_file.parent,
            stop_at=options.output_root / Path(*package_parts),
        )

    return ScaffoldResult(files=tuple(created), version=version)


def _validate_options(options: ScaffoldOptions) -> None:
    if options.version is not None and options.version < 1:
        raise ValueError("version must be >= 1")
    if options.version is not None and options.next:
        raise ValueError("version and next cannot be used together")
    if _USECASE_NAME.fullmatch(options.name) is None:
        raise ValueError("usecase name must look like 'domain.use_case'")


def _resolve_version(
    options: ScaffoldOptions,
    *,
    package_parts: list[str],
    usecase_name: str,
) -> int:
    if options.version is not None:
        return options.version

    usecase_dir = options.output_root / Path(*package_parts) / "usecases" / usecase_name
    versions: list[int] = []
    if usecase_dir.exists():
        for child in usecase_dir.iterdir():
            match = _VERSION_DIR.fullmatch(child.name)
            if match is not None:
                versions.append(int(match.group(1)))
    if options.next:
        if not versions:
            raise ValueError("cannot create next version because no existing versions were found")
        return max(versions) + 1
    if not versions:
        return 1
    return 1


def _write_file(path: Path, content: str, *, force: bool, dry_run: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass force=True to overwrite")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _copy_contract_template(
    previous_contract_file: Path,
    *,
    source_version: int,
    target_version: int,
) -> str:
    if not previous_contract_file.exists():
        raise FileNotFoundError(f"previous contract file does not exist: {previous_contract_file}")

    content = previous_contract_file.read_text()
    content, count = re.subn(
        rf"(\bversion\s*=\s*){source_version}\b",
        rf"\g<1>{target_version}",
        content,
    )
    if count == 0:
        raise ValueError(
            f"could not find version={source_version} in {previous_contract_file}; "
            "pass --version with a fresh scaffold instead"
        )
    content = content.replace(f" v{source_version}", f" v{target_version}")
    content = content.replace(f"@v{source_version}", f"@v{target_version}")
    return content


def _ensure_init_files(directory: Path, *, stop_at: Path) -> None:
    current = directory
    while True:
        init_file = current / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""UseCaseAPI scaffold package."""\n')
        if current == stop_at or current.parent == current:
            break
        current = current.parent


def _camel(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


def _contract_template(
    *,
    name: str,
    version: int,
    class_name: str,
    input_class_name: str,
    output_class_name: str,
    constant_name: str,
) -> str:
    error_name = f"{class_name}Error"
    return f'''from __future__ import annotations

from typing import ClassVar, Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseError, UseCaseRef, define_usecase


class {input_class_name}(Model):
    """Input for {name} v{version}."""


class {output_class_name}(Model):
    """Output for {name} v{version}."""


class {error_name}(UseCaseError):
    """Base domain error for {name} v{version}."""

    code: ClassVar[str] = "{name}"


class {class_name}(
    UseCase[{input_class_name}, {output_class_name}],
    Protocol,
):
    """Contract Protocol for {name} v{version}."""

    async def __call__(
        self,
        input: {input_class_name},
        /,
    ) -> {output_class_name}:
        ...


{constant_name}: UseCaseRef[
    {input_class_name},
    {output_class_name},
] = define_usecase(
    {class_name},
    Contract(
        name="{name}",
        version={version},
        input={input_class_name},
        output={output_class_name},
        raises=({error_name},),
        known_errors=(),
    ),
)
'''


def _implementation_template(
    *,
    usecase_name: str,
    class_name: str,
    input_class_name: str,
    output_class_name: str,
) -> str:
    return f"""from __future__ import annotations

from .{usecase_name}_contract import (
    {input_class_name},
    {output_class_name},
)


class {class_name}:
    async def __call__(
        self,
        input: {input_class_name},
        /,
    ) -> {output_class_name}:
        raise NotImplementedError("Implement {class_name}.__call__")
"""


def _test_template(
    *,
    contract_module: str,
    implementation_module: str,
    usecase_name: str,
    class_name: str,
    usecase_class_name: str,
    constant_name: str,
    name: str,
    version: int,
) -> str:
    return f'''"""Tests for {name} v{version}."""

from __future__ import annotations

from {contract_module} import (
    {constant_name},
    {class_name},
)
from {implementation_module} import {usecase_class_name}


def test_{usecase_name}_contract_metadata() -> None:
    """Contract metadata matches the scaffolded usecase identity."""
    assert {constant_name}.contract.name == "{name}"
    assert {constant_name}.contract.version == {version}


def test_{usecase_name}_usecase_matches_contract() -> None:
    """Usecase implementation structurally matches the contract Protocol."""
    usecase: {class_name} = {usecase_class_name}()
    assert usecase is not None
'''
