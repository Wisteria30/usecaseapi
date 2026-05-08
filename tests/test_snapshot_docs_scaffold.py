from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseAPI, UseCaseRef, define_usecase
from usecaseapi.docs import render_markdown, render_mermaid
from usecaseapi.scaffold import ScaffoldOptions, scaffold_usecase
from usecaseapi.snapshot import diff_snapshots, snapshot_from_api


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


def test_snapshot_docs_and_graph() -> None:
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: ExampleImpl())

    snapshot = snapshot_from_api(api)
    assert snapshot["schema_version"] == 1
    assert snapshot["usecases"][0]["key"] == "example.run@v1"

    docs = render_markdown(api)
    assert "example.run v1" in docs

    graph = render_mermaid(api)
    assert "example.run@v1" in graph


def test_snapshot_diff_detects_schema_change() -> None:
    old = {
        "schema_version": 1,
        "usecases": [
            {
                "key": "example.run@v1",
                "input": {"schema": {"type": "object", "properties": {}}},
                "output": {"schema": {"type": "object", "properties": {}}},
                "raises": [],
                "uses": [],
            }
        ],
    }
    new = json.loads(json.dumps(old))
    new["usecases"][0]["output"] = {"schema": {"type": "object", "properties": {"x": {}}}}

    diff = diff_snapshots(old, new)

    assert diff.has_breaking_changes
    assert diff.breaking == ("changed output schema for example.run@v1",)


def test_scaffold_creates_versioned_contract_and_implementation(tmp_path: Path) -> None:
    result = scaffold_usecase(
        ScaffoldOptions(
            name="orders.place_order",
            version=2,
            contracts_root=tmp_path / "app" / "contracts",
            implementations_root=tmp_path / "app" / "usecases",
            tests_root=tmp_path / "tests",
            force=False,
        )
    )

    files = {file_path.relative_to(tmp_path).as_posix() for file_path in result.files}
    assert "app/contracts/orders/place_order/v2.py" in files
    assert "app/usecases/orders/place_order.py" in files
    assert "tests/test_orders_place_order_v2.py" in files

    contract_text = (tmp_path / "app/contracts/orders/place_order/v2.py").read_text()
    assert "PLACE_ORDER" in contract_text
    assert "version=2" in contract_text


def test_scaffold_next_version_uses_highest_existing_major(tmp_path: Path) -> None:
    contracts_root = tmp_path / "app" / "contracts"
    existing_dir = contracts_root / "orders" / "place_order"
    existing_dir.mkdir(parents=True)
    (existing_dir / "v1.py").write_text("# existing\n")
    (existing_dir / "v3.py").write_text("# existing\n")

    result = scaffold_usecase(
        ScaffoldOptions(
            name="orders.place_order",
            version=None,
            contracts_root=contracts_root,
            implementations_root=tmp_path / "app" / "usecases",
            tests_root=tmp_path / "tests",
        )
    )

    files = {file_path.relative_to(tmp_path).as_posix() for file_path in result.files}
    assert "app/contracts/orders/place_order/v4.py" in files
    assert "tests/test_orders_place_order_v4.py" in files


def test_scaffold_auto_next_version(tmp_path: Path) -> None:
    first = scaffold_usecase(
        ScaffoldOptions(
            name="orders.refund_order",
            version=1,
            contracts_root=tmp_path / "app" / "contracts",
            implementations_root=tmp_path / "app" / "usecases",
            tests_root=tmp_path / "tests",
        )
    )
    second = scaffold_usecase(
        ScaffoldOptions(
            name="orders.refund_order",
            contracts_root=tmp_path / "app" / "contracts",
            implementations_root=tmp_path / "app" / "usecases",
            tests_root=tmp_path / "tests",
        )
    )

    assert first.version == 1
    assert second.version == 2
    assert (tmp_path / "app/contracts/orders/refund_order/v2.py").exists()
    assert tmp_path / "app/usecases/orders/refund_order.py" in second.skipped


def test_scaffold_from_version_copies_previous_contract(tmp_path: Path) -> None:
    scaffold_usecase(
        ScaffoldOptions(
            name="orders.cancel_order",
            version=1,
            contracts_root=tmp_path / "app" / "contracts",
            implementations_root=tmp_path / "app" / "usecases",
            tests_root=tmp_path / "tests",
        )
    )

    result = scaffold_usecase(
        ScaffoldOptions(
            name="orders.cancel_order",
            from_version=1,
            contracts_root=tmp_path / "app" / "contracts",
            implementations_root=tmp_path / "app" / "usecases",
            tests_root=tmp_path / "tests",
        )
    )

    copied_contract = tmp_path / "app/contracts/orders/cancel_order/v2.py"
    assert result.version == 2
    assert copied_contract.exists()
    assert "version=2" in copied_contract.read_text()
    assert "version=1" not in copied_contract.read_text()
