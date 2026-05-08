from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_USECASE_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_VERSION_FILE = re.compile(r"^v([1-9][0-9]*)\.py$")


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    """Files planned or created by the scaffold command."""

    files: tuple[Path, ...]
    skipped: tuple[Path, ...] = ()
    version: int = 1


@dataclass(frozen=True, slots=True)
class ScaffoldOptions:
    """Options for creating a versioned usecase skeleton.

    ``version=None`` means "create the next available major version". If
    ``from_version`` is set and ``version`` is omitted, the target version is
    ``from_version + 1`` and the previous contract is copied forward with the
    contract metadata updated.
    """

    name: str
    version: int | None = None
    from_version: int | None = None
    contracts_root: Path = Path("app/contracts")
    implementations_root: Path = Path("app/usecases")
    tests_root: Path = Path("tests")
    contracts_package: str = "app.contracts"
    implementations_package: str = "app.usecases"
    force: bool = False
    dry_run: bool = False
    create_implementation: bool = True
    create_tests: bool = True
    create_init: bool = True


def scaffold_usecase(options: ScaffoldOptions) -> ScaffoldResult:
    """Create contract, implementation, and optional test files for one usecase."""

    if options.version is not None and options.version < 1:
        raise ValueError("version must be >= 1")
    if options.from_version is not None and options.from_version < 1:
        raise ValueError("from_version must be >= 1")
    if _USECASE_NAME.fullmatch(options.name) is None:
        raise ValueError("usecase name must look like 'domain.use_case'")

    parts = options.name.split(".")
    domain_parts = parts[:-1]
    usecase_name = parts[-1]
    version = _resolve_version(options, domain_parts=domain_parts, usecase_name=usecase_name)
    if options.from_version is not None and options.from_version >= version:
        raise ValueError("from_version must be lower than target version")

    class_name = _camel(usecase_name)
    constant_name = usecase_name.upper()

    contract_dir = options.contracts_root / Path(*domain_parts) / usecase_name
    contract_file = contract_dir / f"v{version}.py"
    implementation_file = options.implementations_root / Path(*domain_parts) / f"{usecase_name}.py"
    test_file = options.tests_root / f"test_{'_'.join(parts)}_v{version}.py"

    contract_module = ".".join(
        [options.contracts_package, *domain_parts, usecase_name, f"v{version}"]
    )
    implementation_module = ".".join([options.implementations_package, *domain_parts, usecase_name])

    if options.from_version is None:
        contract_content = _contract_template(
            name=options.name,
            version=version,
            class_name=class_name,
            constant_name=constant_name,
        )
    else:
        previous_contract_file = contract_dir / f"v{options.from_version}.py"
        contract_content = _copy_contract_template(
            previous_contract_file,
            from_version=options.from_version,
            target_version=version,
        )

    created: list[Path] = []
    skipped: list[Path] = []

    _write_file(contract_file, contract_content, force=options.force, dry_run=options.dry_run)
    created.append(contract_file)

    if options.create_implementation:
        implementation_content = _implementation_template(
            contract_module=contract_module,
            class_name=class_name,
        )
        if implementation_file.exists() and not options.force:
            skipped.append(implementation_file)
        else:
            _write_file(
                implementation_file,
                implementation_content,
                force=options.force,
                dry_run=options.dry_run,
            )
            created.append(implementation_file)

    if options.create_tests:
        _write_file(
            test_file,
            _test_template(
                contract_module=contract_module,
                implementation_module=implementation_module,
                class_name=class_name,
                constant_name=constant_name,
                name=options.name,
                version=version,
            ),
            force=options.force,
            dry_run=options.dry_run,
        )
        created.append(test_file)

    if options.create_init and not options.dry_run:
        _ensure_init_files(contract_file.parent, stop_at=options.contracts_root.parent)
        if options.create_implementation:
            _ensure_init_files(
                implementation_file.parent,
                stop_at=options.implementations_root.parent,
            )

    return ScaffoldResult(files=tuple(created), skipped=tuple(skipped), version=version)


def _resolve_version(
    options: ScaffoldOptions,
    *,
    domain_parts: list[str],
    usecase_name: str,
) -> int:
    if options.version is not None:
        return options.version
    if options.from_version is not None:
        return options.from_version + 1

    contract_dir = options.contracts_root / Path(*domain_parts) / usecase_name
    versions: list[int] = []
    if contract_dir.exists():
        for child in contract_dir.iterdir():
            match = _VERSION_FILE.fullmatch(child.name)
            if match is not None:
                versions.append(int(match.group(1)))
    if not versions:
        return 1
    return max(versions) + 1


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
    from_version: int,
    target_version: int,
) -> str:
    if not previous_contract_file.exists():
        raise FileNotFoundError(f"previous contract file does not exist: {previous_contract_file}")

    content = previous_contract_file.read_text()
    content, count = re.subn(
        rf"(\bversion\s*=\s*){from_version}\b",
        rf"\g<1>{target_version}",
        content,
    )
    if count == 0:
        raise ValueError(
            f"could not find version={from_version} in {previous_contract_file}; "
            "pass --version with a fresh scaffold instead"
        )
    content = content.replace(f" v{from_version}", f" v{target_version}")
    content = content.replace(f"@v{from_version}", f"@v{target_version}")
    return content


def _ensure_init_files(directory: Path, *, stop_at: Path) -> None:
    current = directory
    while True:
        init_file = current / "__init__.py"
        if not init_file.exists():
            init_file.write_text("")
        if current == stop_at or current.parent == current:
            break
        current = current.parent


def _camel(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


def _contract_template(*, name: str, version: int, class_name: str, constant_name: str) -> str:
    error_name = f"{class_name}Error"
    return f'''from __future__ import annotations

from typing import ClassVar, Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseError, UseCaseRef, define_usecase


class Input(Model):
    """Input for {name} v{version}."""


class Output(Model):
    """Output for {name} v{version}."""


class {error_name}(UseCaseError):
    """Base domain error for {name} v{version}."""

    code: ClassVar[str] = "{name}"


class {class_name}(UseCase[Input, Output], Protocol):
    """Contract Protocol for {name} v{version}."""

    async def __call__(self, input: Input, /) -> Output:
        ...


{constant_name}: UseCaseRef[Input, Output] = define_usecase(
    {class_name},
    Contract(
        name="{name}",
        version={version},
        input=Input,
        output=Output,
        raises=({error_name},),
        known_errors=(),
    ),
)
'''


def _implementation_template(*, contract_module: str, class_name: str) -> str:
    return f"""from __future__ import annotations

from {contract_module} import Input, Output, {class_name}


class {class_name}Impl:
    async def __call__(self, input: Input, /) -> Output:
        raise NotImplementedError("Implement {class_name}Impl.__call__")


_impl: {class_name} = {class_name}Impl()
"""


def _test_template(
    *,
    contract_module: str,
    implementation_module: str,
    class_name: str,
    constant_name: str,
    name: str,
    version: int,
) -> str:
    return f'''from __future__ import annotations

from {contract_module} import {class_name}, {constant_name}
from {implementation_module} import {class_name}Impl


def test_{constant_name.lower()}_contract_metadata() -> None:
    assert {constant_name}.contract.name == "{name}"
    assert {constant_name}.contract.version == {version}


def test_{constant_name.lower()}_implementation_matches_protocol() -> None:
    _impl: {class_name} = {class_name}Impl()
    assert _impl is not None
'''
