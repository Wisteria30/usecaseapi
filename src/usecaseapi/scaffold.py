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


@dataclass(frozen=True, slots=True)
class ScaffoldNames:
    """Derived Python identifiers for one scaffolded usecase."""

    package_parts: tuple[str, ...]
    usecase_name: str
    class_name: str
    constant_name: str
    usecase_class_name: str
    input_class_name: str
    output_class_name: str

    @classmethod
    def from_contract_name(cls, name: str) -> ScaffoldNames:
        """Derive scaffold identifiers from a dotted usecase contract name."""
        parts = name.split(".")
        usecase_name = parts[-1]
        class_name = camel_class_name(usecase_name)
        usecase_class_name = f"{class_name}UseCase"
        return cls(
            package_parts=tuple(parts[:-1]),
            usecase_name=usecase_name,
            class_name=class_name,
            constant_name=f"{usecase_name.upper()}_USECASE",
            usecase_class_name=usecase_class_name,
            input_class_name=f"{usecase_class_name}Input",
            output_class_name=f"{usecase_class_name}Output",
        )


@dataclass(frozen=True, slots=True)
class ScaffoldLayout:
    """Filesystem and import paths for one scaffolded usecase version."""

    contract_file: Path
    implementation_file: Path
    test_file: Path
    contract_module: str
    implementation_module: str
    package_root: Path

    @classmethod
    def from_options(
        cls,
        options: ScaffoldOptions,
        *,
        names: ScaffoldNames,
        version: int,
    ) -> ScaffoldLayout:
        """Derive filesystem and module paths from scaffold options."""
        package_path = Path(*names.package_parts)
        version_dir = (
            options.output_root / package_path / "usecases" / names.usecase_name / f"v{version}"
        )
        module_parts = [
            *names.package_parts,
            "usecases",
            names.usecase_name,
            f"v{version}",
        ]
        return cls(
            contract_file=version_dir / f"{names.usecase_name}_contract.py",
            implementation_file=version_dir / f"{names.usecase_name}_usecase.py",
            test_file=(
                options.tests_root
                / package_path
                / "usecases"
                / names.usecase_name
                / f"v{version}"
                / f"test_{names.usecase_name}.py"
            ),
            contract_module=".".join([*module_parts, f"{names.usecase_name}_contract"]),
            implementation_module=".".join([*module_parts, f"{names.usecase_name}_usecase"]),
            package_root=options.output_root / package_path,
        )

    def previous_contract_file(self, names: ScaffoldNames, *, version: int) -> Path:
        """Return the contract file path for a previous scaffold version."""
        return self.contract_file.parents[1] / f"v{version}" / f"{names.usecase_name}_contract.py"


def scaffold_usecase(options: ScaffoldOptions) -> ScaffoldResult:
    """Create contract, implementation, and optional test files for one usecase."""
    validate_scaffold_options(options)
    names = ScaffoldNames.from_contract_name(options.name)
    version = resolve_scaffold_version(
        options,
        package_parts=list(names.package_parts),
        usecase_name=names.usecase_name,
    )
    layout = ScaffoldLayout.from_options(options, names=names, version=version)

    if options.next:
        contract_content = copy_previous_contract_version(
            layout.previous_contract_file(names, version=version - 1),
            source_version=version - 1,
            target_version=version,
        )
    else:
        contract_content = contract_template(
            name=options.name,
            version=version,
            class_name=names.class_name,
            input_class_name=names.input_class_name,
            output_class_name=names.output_class_name,
            constant_name=names.constant_name,
        )

    created: list[Path] = []

    write_scaffold_file(
        layout.contract_file,
        contract_content,
        force=options.force,
        dry_run=options.dry_run,
    )
    created.append(layout.contract_file)

    write_scaffold_file(
        layout.implementation_file,
        implementation_template(
            usecase_name=names.usecase_name,
            class_name=names.usecase_class_name,
            input_class_name=names.input_class_name,
            output_class_name=names.output_class_name,
        ),
        force=options.force,
        dry_run=options.dry_run,
    )
    created.append(layout.implementation_file)

    write_scaffold_file(
        layout.test_file,
        test_template(
            contract_module=layout.contract_module,
            implementation_module=layout.implementation_module,
            usecase_name=names.usecase_name,
            class_name=names.class_name,
            usecase_class_name=names.usecase_class_name,
            constant_name=names.constant_name,
            name=options.name,
            version=version,
        ),
        force=options.force,
        dry_run=options.dry_run,
    )
    created.append(layout.test_file)

    if not options.dry_run:
        ensure_init_files(
            layout.contract_file.parent,
            stop_at=layout.package_root,
        )

    return ScaffoldResult(files=tuple(created), version=version)


def validate_scaffold_options(options: ScaffoldOptions) -> None:
    """Validate scaffold options before deriving paths or writing files."""
    if options.version is not None and options.version < 1:
        raise ValueError("version must be >= 1")
    if options.version is not None and options.next:
        raise ValueError("version and next cannot be used together")
    if _USECASE_NAME.fullmatch(options.name) is None:
        raise ValueError("usecase name must look like 'domain.use_case'")


def resolve_scaffold_version(
    options: ScaffoldOptions,
    *,
    package_parts: list[str],
    usecase_name: str,
) -> int:
    """Resolve the target scaffold version from explicit and next-version options."""
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


def write_scaffold_file(path: Path, content: str, *, force: bool, dry_run: bool) -> None:
    """Write one scaffolded file with explicit overwrite behavior."""
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass force=True to overwrite")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def copy_previous_contract_version(
    previous_contract_file: Path,
    *,
    source_version: int,
    target_version: int,
) -> str:
    """Copy a previous contract version and update supported version markers."""
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


def ensure_init_files(directory: Path, *, stop_at: Path) -> None:
    """Create package marker files from a scaffold directory up to the package root."""
    current = directory
    while True:
        init_file = current / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""UseCaseAPI scaffold package."""\n')
        if current == stop_at or current.parent == current:
            break
        current = current.parent


def camel_class_name(value: str) -> str:
    """Convert a snake_case usecase name into a PascalCase class stem."""
    return "".join(part.capitalize() for part in value.split("_"))


def contract_template(
    *,
    name: str,
    version: int,
    class_name: str,
    input_class_name: str,
    output_class_name: str,
    constant_name: str,
) -> str:
    """Render the Python contract module for a scaffolded usecase."""
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


def implementation_template(
    *,
    usecase_name: str,
    class_name: str,
    input_class_name: str,
    output_class_name: str,
) -> str:
    """Render the Python implementation module for a scaffolded usecase."""
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


def test_template(
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
    """Render the pytest module for a scaffolded usecase."""
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
