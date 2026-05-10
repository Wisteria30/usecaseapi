"""Scaffold behavior tests."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pytest

from usecaseapi import Contract, Model, UseCase, UseCaseRef, define_usecase
from usecaseapi.scaffold import ScaffoldOptions, scaffold_usecase


class Input(Model):
    value: int


class Output(Model):
    value: int


class Example(UseCase[Input, Output], Protocol):
    async def __call__(self, input: Input, /) -> Output: ...


EXAMPLE: UseCaseRef[Input, Output] = define_usecase(
    Example,
    Contract(name="example.run", version=1, input=Input, output=Output),
)


class ExampleImpl:
    async def __call__(self, input: Input, /) -> Output:
        return Output(value=input.value)


def test_scaffold_creates_versioned_contract_and_implementation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scaffold creates a versioned contract, implementation, and test file."""
    monkeypatch.chdir(tmp_path)
    result = scaffold_usecase(
        ScaffoldOptions(
            output_root=Path("src"),
            name="commerce.place_order",
            version=2,
            force=False,
        )
    )

    files = {file_path.as_posix() for file_path in result.files}
    assert "src/commerce/usecases/place_order/v2/place_order_contract.py" in files
    assert "src/commerce/usecases/place_order/v2/place_order_usecase.py" in files
    assert "tests/commerce/usecases/place_order/v2/test_place_order.py" in files

    contract_text = (
        tmp_path / "src/commerce/usecases/place_order/v2/place_order_contract.py"
    ).read_text()
    assert "PLACE_ORDER_USECASE" in contract_text
    assert "class PlaceOrderUseCaseInput(Model):" in contract_text
    assert "class PlaceOrderUseCaseOutput(Model):" in contract_text
    assert "UseCase[PlaceOrderUseCaseInput, PlaceOrderUseCaseOutput]," in contract_text
    assert "PLACE_ORDER_USECASE: UseCaseRef[" in contract_text
    assert "    PlaceOrderUseCaseInput," in contract_text
    assert "    PlaceOrderUseCaseOutput," in contract_text
    assert "version=2" in contract_text
    usecase_text = (
        tmp_path / "src/commerce/usecases/place_order/v2/place_order_usecase.py"
    ).read_text()
    assert "class PlaceOrderUseCase" in usecase_text
    assert "from .place_order_contract import (" in usecase_text
    assert "    PlaceOrderUseCaseInput," in usecase_text
    assert "    PlaceOrderUseCaseOutput," in usecase_text
    assert "async def __call__(" in usecase_text
    assert "        input: PlaceOrderUseCaseInput," in usecase_text
    assert "    ) -> PlaceOrderUseCaseOutput:" in usecase_text
    assert "dataclass" not in usecase_text


def test_scaffold_next_version_uses_highest_existing_major(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scaffold --next chooses the next major version after existing version files."""
    monkeypatch.chdir(tmp_path)
    scaffold_usecase(
        ScaffoldOptions(
            output_root=Path("src"),
            name="commerce.place_order",
            version=3,
        )
    )

    result = scaffold_usecase(
        ScaffoldOptions(
            output_root=Path("src"),
            name="commerce.place_order",
            next=True,
        )
    )

    files = {file_path.as_posix() for file_path in result.files}
    assert "src/commerce/usecases/place_order/v4/place_order_contract.py" in files
    assert "tests/commerce/usecases/place_order/v4/test_place_order.py" in files


def test_scaffold_without_version_creates_v1_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scaffold without version creates v1 and does not automatically increment."""
    monkeypatch.chdir(tmp_path)
    first = scaffold_usecase(
        ScaffoldOptions(
            output_root=Path("src"),
            name="commerce.refund_order",
        )
    )
    with pytest.raises(FileExistsError):
        scaffold_usecase(
            ScaffoldOptions(
                output_root=Path("src"),
                name="commerce.refund_order",
            )
        )

    assert first.version == 1
    assert (tmp_path / "src/commerce/usecases/refund_order/v1/refund_order_contract.py").exists()
    assert not (tmp_path / "src/commerce/usecases/refund_order/v2").exists()


def test_scaffold_next_copies_latest_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scaffold --next copies the latest contract version and updates metadata."""
    monkeypatch.chdir(tmp_path)
    scaffold_usecase(
        ScaffoldOptions(
            output_root=Path("src"),
            name="commerce.cancel_order",
            version=1,
        )
    )

    result = scaffold_usecase(
        ScaffoldOptions(
            output_root=Path("src"),
            name="commerce.cancel_order",
            next=True,
        )
    )

    copied_contract = tmp_path / "src/commerce/usecases/cancel_order/v2/cancel_order_contract.py"
    assert result.version == 2
    assert copied_contract.exists()
    assert "version=2" in copied_contract.read_text()
    assert "version=1" not in copied_contract.read_text()
