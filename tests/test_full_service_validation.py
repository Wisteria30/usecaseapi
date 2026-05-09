from __future__ import annotations

import asyncio
import json
import runpy
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

import pytest

from usecaseapi import (
    Contract,
    ContractDefinitionError,
    DuplicateUseCaseError,
    InvalidHandlerError,
    MissingBindingError,
    Model,
    UndeclaredUseCaseError,
    UseCase,
    UseCaseAPI,
    UseCaseError,
    UseCaseRef,
    define_usecase,
)
from usecaseapi.api import Binding
from usecaseapi.cli import main
from usecaseapi.docs import render_markdown, render_mermaid
from usecaseapi.scaffold import ScaffoldOptions, scaffold_usecase
from usecaseapi.snapshot import (
    ContractDiff,
    diff_snapshots,
    load_snapshot,
    write_snapshot,
)


class Input(Model):
    value: int


class Output(Model):
    value: int


class EmptyInput(Model):
    pass


class EmptyOutput(Model):
    pass


class ExampleError(UseCaseError):
    code: ClassVar[str] = "example"


class KnownExampleError(ExampleError):
    code: ClassVar[str] = "example.known"


class OtherError(UseCaseError):
    code: ClassVar[str] = "other"


class Example(UseCase[Input, Output], Protocol):
    async def __call__(self, input: Input, /) -> Output: ...


class EmptyExample(UseCase[EmptyInput, EmptyOutput], Protocol):
    async def __call__(self, input: EmptyInput, /) -> EmptyOutput: ...


EXAMPLE: UseCaseRef[Input, Output] = define_usecase(
    Example,
    Contract(
        name="example.run",
        version=1,
        input=Input,
        output=Output,
        raises=(ExampleError,),
        known_errors=(KnownExampleError,),
        description="Example contract.",
        tags=("demo",),
    ),
)

EMPTY: UseCaseRef[EmptyInput, EmptyOutput] = define_usecase(
    EmptyExample,
    Contract(
        name="empty.run",
        version=1,
        input=EmptyInput,
        output=EmptyOutput,
        deprecated=True,
        superseded_by="empty.run@v2",
    ),
)


class GoodImpl:
    async def __call__(self, input: Input, /) -> Output:
        return Output(value=input.value + 1)


class EmptyImpl:
    async def __call__(self, input: EmptyInput, /) -> EmptyOutput:
        return EmptyOutput()


async def function_handler(input: Input, /) -> Output:
    return Output(value=input.value + 10)


def run_call(api: UseCaseAPI[None], input: Input | EmptyInput | None = None) -> Any:
    if input is None:
        input = Input(value=1)
    ref: Any = EMPTY if isinstance(input, EmptyInput) else EXAMPLE
    return asyncio.run(api.caller(None).call(ref, input))


def test_contract_definition_guards_and_ref_properties() -> None:
    with pytest.raises(ContractDefinitionError, match="name"):
        Contract(name=" ", version=1, input=Input, output=Output)
    with pytest.raises(ContractDefinitionError, match="version"):
        Contract(name="bad.version", version=0, input=Input, output=Output)
    with pytest.raises(ContractDefinitionError, match="input"):
        Contract(name="bad.input", version=1, input=cast(Any, object), output=Output)
    with pytest.raises(ContractDefinitionError, match="output"):
        Contract(name="bad.output", version=1, input=Input, output=cast(Any, object))
    with pytest.raises(ContractDefinitionError, match="errors"):
        Contract(
            name="bad.error",
            version=1,
            input=Input,
            output=Output,
            raises=(cast(Any, ValueError),),
        )
    with pytest.raises(ContractDefinitionError, match="covered"):
        Contract(
            name="bad.known",
            version=1,
            input=Input,
            output=Output,
            raises=(ExampleError,),
            known_errors=(OtherError,),
        )
    with pytest.raises(ContractDefinitionError, match="Protocol"):
        define_usecase(object, Contract(name="bad.protocol", version=1, input=Input, output=Output))

    assert EXAMPLE.key == "example.run@v1"
    assert EXAMPLE.name == "example.run"
    assert EXAMPLE.version == 1
    assert repr(EXAMPLE) == "UseCaseRef(example.run@v1)"


def test_usecase_api_registry_validation_and_metadata() -> None:
    api = UseCaseAPI[None]()
    api.register(EXAMPLE)
    duplicate = define_usecase(
        Example,
        Contract(name="example.run", version=1, input=Input, output=Output),
    )

    with pytest.raises(DuplicateUseCaseError):
        api.register(duplicate)
    with pytest.raises(MissingBindingError, match="missing usecase bindings"):
        api.validate()

    api.bind(EXAMPLE, lambda caller: GoodImpl(), description="primary", tags=("fast",))
    with pytest.raises(DuplicateUseCaseError):
        api.bind(EXAMPLE, lambda caller: GoodImpl())

    binding = api.bindings[0]
    assert binding.description == "primary"
    assert binding.tags == ("fast",)

    broken_api = UseCaseAPI[None]()
    broken_api.bind(EXAMPLE, lambda caller: GoodImpl())
    broken_api._bindings[EXAMPLE.key] = Binding(
        ref=EXAMPLE,
        factory=lambda caller: GoodImpl(),
        uses=frozenset({"missing.usecase@v1"}),
    )
    with pytest.raises(MissingBindingError, match="declares unknown uses"):
        broken_api.validate(require_handlers=False)


def test_handler_validation_rejects_invalid_runtime_shapes() -> None:
    class SyncImpl:
        def __call__(self, input: Input, /) -> Output:
            return Output(value=input.value)

    class TooManyArgsImpl:
        async def __call__(self, input: Input, extra: Input) -> Output:
            return Output(value=input.value + extra.value)

    class MissingInputAnnotationImpl:
        async def __call__(self, input, /) -> Output:  # type: ignore[no-untyped-def]
            return Output(value=input.value)

    class MissingReturnAnnotationImpl:
        async def __call__(self, input: Input, /):  # type: ignore[no-untyped-def]
            return Output(value=input.value)

    class WrongInputAnnotationImpl:
        async def __call__(self, input: EmptyInput, /) -> Output:
            return Output(value=1)

    class WrongReturnAnnotationImpl:
        async def __call__(self, input: Input, /) -> EmptyOutput:
            return EmptyOutput()

    class ReturnsPlainValueImpl:
        async def __call__(self, input: Input, /) -> Output:
            return Output(value=input.value)

    class ReturnsWrongOutputImpl:
        async def __call__(self, input: Input, /) -> Output:
            return cast(Output, EmptyOutput())

    cases: tuple[tuple[Callable[[], Any], str], ...] = (
        (SyncImpl, "must be async"),
        (TooManyArgsImpl, "exactly one positional"),
        (MissingInputAnnotationImpl, "annotate input"),
        (MissingReturnAnnotationImpl, "annotate return"),
        (WrongInputAnnotationImpl, "input annotation"),
        (WrongReturnAnnotationImpl, "return annotation"),
    )
    for factory, message in cases:
        api = UseCaseAPI[None]()
        api.bind(EXAMPLE, _handler_factory(factory))
        with pytest.raises(InvalidHandlerError, match=message):
            run_call(api)

    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: cast(Any, 1))
    with pytest.raises(InvalidHandlerError, match="not callable"):
        run_call(api)

    api = UseCaseAPI[None](validate_handlers=False)
    api.bind(EXAMPLE, lambda caller: cast(Any, lambda input: Output(value=input.value)))
    with pytest.raises(InvalidHandlerError, match="awaitable"):
        run_call(api)

    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: ReturnsWrongOutputImpl())
    with pytest.raises(InvalidHandlerError, match="returned EmptyOutput"):
        run_call(api)

    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: function_handler)
    assert run_call(api) == Output(value=11)

    api = UseCaseAPI[None]()
    impl = ReturnsPlainValueImpl()
    api.bind(EXAMPLE, lambda caller: impl)
    assert run_call(api) == Output(value=1)
    assert run_call(api) == Output(value=1)


def test_caller_records_gather_and_error_policy() -> None:
    api = UseCaseAPI[None](strict_errors=False)
    api.bind(EXAMPLE, lambda caller: GoodImpl())
    caller = api.caller(None)
    result = asyncio.run(
        caller.gather(
            caller.call(EXAMPLE, Input(value=1)),
            caller.call(EXAMPLE, Input(value=2)),
        )
    )

    assert result == (Output(value=2), Output(value=3))
    assert [record.callee_key for record in caller.records] == ["example.run@v1", "example.run@v1"]

    class RaisesGroupImpl:
        async def __call__(self, input: Input, /) -> Output:
            raise ExceptionGroup("group", [ValueError("plain"), OtherError("domain")])

    class RaisesOtherImpl:
        async def __call__(self, input: Input, /) -> Output:
            raise OtherError("accepted by configuration")

    strict_api = UseCaseAPI[None]()
    strict_api.bind(EXAMPLE, lambda caller: RaisesGroupImpl())
    with pytest.raises(UndeclaredUseCaseError) as exc_info:
        run_call(strict_api)
    assert isinstance(exc_info.value.error, OtherError)

    relaxed_api = UseCaseAPI[None](strict_errors=False)
    relaxed_api.bind(EXAMPLE, lambda caller: RaisesOtherImpl())
    with pytest.raises(OtherError):
        run_call(relaxed_api)

    missing_api = UseCaseAPI[None]()
    with pytest.raises(MissingBindingError, match="missing binding"):
        run_call(missing_api)


def test_docs_snapshot_and_diff_cover_contract_catalog(tmp_path: Path) -> None:
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: GoodImpl(), uses=(EMPTY,))
    api.bind(EMPTY, lambda caller: EmptyImpl())

    markdown = render_markdown(api)
    assert "Example contract." in markdown
    assert "KnownExampleError" in markdown
    assert "Superseded by: `empty.run@v2`" in markdown
    assert "- No fields" in markdown
    assert "`empty.run@v1`" in markdown

    graph = render_mermaid(api)
    assert "uc_example_run_v1 --> uc_empty_run_v1" in graph

    snapshot_path = tmp_path / "snapshot.json"
    write_snapshot(api, snapshot_path)
    snapshot = load_snapshot(snapshot_path)
    assert snapshot["usecases"][0]["key"] == "empty.run@v1"
    assert snapshot["usecases"][1]["raises"][0]["parents"]

    diff = diff_snapshots(
        {
            "usecases": [
                {
                    "key": "example.run@v1",
                    "input": "old",
                    "output": "same",
                    "raises": [{"code": "example"}],
                    "uses": ["empty.run@v1"],
                    "deprecated": False,
                },
                {"key": "removed.run@v1"},
            ]
        },
        {
            "usecases": [
                {
                    "key": "example.run@v1",
                    "input": "new",
                    "output": "same",
                    "raises": [],
                    "uses": [],
                    "deprecated": True,
                },
                {"key": "added.run@v1"},
            ]
        },
    )
    assert diff.breaking == (
        "removed usecase removed.run@v1",
        "changed input schema for example.run@v1",
        "removed declared errors for example.run@v1: example",
    )
    assert diff.warnings == (
        "removed declared uses for example.run@v1: empty.run@v1",
        "deprecated usecase example.run@v1",
    )
    assert diff.additions == ("added usecase added.run@v1",)
    assert diff.to_dict()["breaking"] == list(diff.breaking)
    assert ContractDiff((), (), ()).has_breaking_changes is False

    unchanged = diff_snapshots(
        {"usecases": [{"key": "same.run@v1"}]},
        {"usecases": [{"key": "same.run@v1"}]},
    )
    assert unchanged == ContractDiff((), (), ())

    for payload, message in (
        ([], "snapshot must be a JSON object"),
        ({"usecases": {}}, "snapshot.usecases must be a list"),
        ({"usecases": [None]}, "snapshot usecase must be an object"),
        ({"usecases": [{}]}, "snapshot usecase key must be a string"),
    ):
        path = tmp_path / f"{message.split()[0]}.json"
        path.write_text(json.dumps(payload))
        with pytest.raises(ValueError, match=message):
            load_snapshot(path) if isinstance(payload, list) else diff_snapshots(payload, payload)


def test_scaffold_boundaries_and_dry_run(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="version"):
        scaffold_usecase(ScaffoldOptions(name="orders.create", version=0))
    with pytest.raises(ValueError, match="from_version"):
        scaffold_usecase(ScaffoldOptions(name="orders.create", from_version=0))
    with pytest.raises(ValueError, match=r"domain\.use_case"):
        scaffold_usecase(ScaffoldOptions(name="orders"))
    with pytest.raises(ValueError, match="lower"):
        scaffold_usecase(
            ScaffoldOptions(
                name="orders.create",
                version=1,
                from_version=1,
                contracts_root=tmp_path / "contracts",
            )
        )
    with pytest.raises(FileNotFoundError):
        scaffold_usecase(
            ScaffoldOptions(
                name="orders.create",
                from_version=1,
                contracts_root=tmp_path / "contracts",
            )
        )

    previous = tmp_path / "contracts" / "orders" / "create" / "v1.py"
    previous.parent.mkdir(parents=True)
    previous.write_text("VERSION = 1\n")
    with pytest.raises(ValueError, match="could not find version=1"):
        scaffold_usecase(
            ScaffoldOptions(
                name="orders.create",
                from_version=1,
                contracts_root=tmp_path / "contracts",
            )
        )

    dry_root = tmp_path / "dry"
    result = scaffold_usecase(
        ScaffoldOptions(
            name="orders.reserve",
            contracts_root=dry_root / "contracts",
            implementations_root=dry_root / "usecases",
            tests_root=dry_root / "tests",
            dry_run=True,
            create_implementation=False,
            create_tests=False,
        )
    )
    assert result.version == 1
    assert result.files == (dry_root / "contracts" / "orders" / "reserve" / "v1.py",)
    assert not dry_root.exists()

    created = scaffold_usecase(
        ScaffoldOptions(
            name="orders.reserve",
            contracts_root=tmp_path / "real" / "contracts",
            implementations_root=tmp_path / "real" / "usecases",
            tests_root=tmp_path / "real" / "tests",
        )
    )
    with pytest.raises(FileExistsError):
        scaffold_usecase(
            ScaffoldOptions(
                name="orders.reserve",
                version=1,
                contracts_root=tmp_path / "real" / "contracts",
                implementations_root=tmp_path / "real" / "usecases",
                tests_root=tmp_path / "real" / "tests",
            )
        )
    assert created.files[0].exists()


def test_cli_commands_validate_service_surface(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    example_root = Path(__file__).parents[1] / "examples" / "basic"
    sys.path.insert(0, str(example_root))
    try:
        assert main(["check", "app.composition:usecases"]) == 0
        assert "UseCaseAPI check passed" in capsys.readouterr().out

        assert main(["inspect", "app.composition:usecases"]) == 0
        inspect_output = json.loads(capsys.readouterr().out)
        assert {item["key"] for item in inspect_output["usecases"]} == {
            "checkout.checkout@v1",
            "inventory.check_availability@v1",
            "orders.place_order@v1",
        }

        docs_path = tmp_path / "docs.md"
        graph_path = tmp_path / "graph.mmd"
        snapshot_path = tmp_path / "snapshot.json"
        assert main(["docs", "app.composition:usecases", "--output", str(docs_path)]) == 0
        assert main(["graph", "app.composition:usecases", "-o", str(graph_path)]) == 0
        assert main(["snapshot", "app.composition:usecases", "-o", str(snapshot_path)]) == 0
        assert "checkout.checkout v1" in docs_path.read_text()
        assert "orders.place_order@v1" in graph_path.read_text()
        assert load_snapshot(snapshot_path)["schema_version"] == 1

        scaffold_root = tmp_path / "generated"
        assert (
            main(
                [
                    "scaffold",
                    "billing.capture_payment",
                    "--contracts-root",
                    str(scaffold_root / "contracts"),
                    "--implementations-root",
                    str(scaffold_root / "usecases"),
                    "--tests-root",
                    str(scaffold_root / "tests"),
                    "--contracts-package",
                    "generated.contracts",
                    "--implementations-package",
                    "generated.usecases",
                    "--no-tests",
                    "--no-init",
                ]
            )
            == 0
        )
        scaffold_output = capsys.readouterr().out
        assert "scaffolded version: v1" in scaffold_output
        assert "capture_payment/v1.py" in scaffold_output

        assert (
            main(
                [
                    "scaffold",
                    "billing.capture_payment",
                    "--next",
                    "--contracts-root",
                    str(scaffold_root / "contracts"),
                    "--implementations-root",
                    str(scaffold_root / "usecases"),
                    "--tests-root",
                    str(scaffold_root / "tests"),
                    "--contracts-package",
                    "generated.contracts",
                    "--implementations-package",
                    "generated.usecases",
                    "--no-tests",
                    "--no-init",
                ]
            )
            == 0
        )
        assert "skipped:" in capsys.readouterr().out

        assert main(["diff", str(snapshot_path), str(snapshot_path)]) == 0
        assert "Breaking:\n  - none" in capsys.readouterr().out
        assert main(["diff", str(snapshot_path), str(snapshot_path), "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == {
            "breaking": [],
            "warnings": [],
            "additions": [],
        }

        changed_path = tmp_path / "changed.json"
        changed = load_snapshot(snapshot_path)
        changed["usecases"] = changed["usecases"][1:]
        changed_path.write_text(json.dumps(changed))
        assert main(["diff", str(snapshot_path), str(changed_path)]) == 1
        assert "removed usecase" in capsys.readouterr().out

        assert main(["snapshot", "app.composition:usecases"]) == 0
        assert "checkout.checkout@v1" in capsys.readouterr().out
    finally:
        sys.path.remove(str(example_root))


def test_cli_import_path_errors_and_main_module(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(ValueError, match="module:attribute"):
        main(["check", "not-an-import-path"])
    with pytest.raises(TypeError, match="UseCaseAPI"):
        main(["check", "json:loads"])

    class Parsed:
        command = "unknown"

    class Parser:
        def parse_args(self, argv: object) -> Parsed:
            return Parsed()

        def print_help(self) -> None:
            print("help from fake parser")

    monkeypatch.setattr("usecaseapi.cli._build_parser", lambda: Parser())
    assert main([]) == 2
    assert "help from fake parser" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["usecaseapi", "--help"])
    sys.modules.pop("usecaseapi.cli", None)
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("usecaseapi.cli", run_name="__main__")
    assert exc_info.value.code == 0


def test_usecase_error_serialization() -> None:
    error = OtherError("domain failed")
    cast(Any, error).reason = "inventory"

    assert error.details == {"reason": "inventory"}
    assert error.to_dict() == {
        "type": "test_full_service_validation.OtherError",
        "code": "other",
        "message": "domain failed",
        "details": {"reason": "inventory"},
    }


def _handler_factory(factory: Callable[[], Any]) -> Callable[[object], Any]:
    def create(_caller: object) -> Any:
        return factory()

    return create
