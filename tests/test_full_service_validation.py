"""Full service validation tests for packaging, CLI, and runtime behavior."""

from __future__ import annotations

import asyncio
import json
import runpy
import sys

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar, Protocol, cast

import pytest
import yaml

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
from usecaseapi.manifest import (
    ManifestDiff,
    diff_manifests,
    load_manifest,
    manifest_from_api,
    render_manifest_graph,
    render_manifest_markdown,
)
from usecaseapi.scaffold import ScaffoldOptions, ScaffoldResult, scaffold_usecase


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
    """Function-style handler used to validate callable target detection."""
    return Output(value=input.value + 10)


def run_call(api: UseCaseAPI[None], input: Input | EmptyInput | None = None) -> Any:
    """Run a single call against the example or empty reference."""
    if input is None:
        input = Input(value=1)
    ref: Any = EMPTY if isinstance(input, EmptyInput) else EXAMPLE
    return asyncio.run(api.caller(None).call(ref, input))


def test_contract_definition_guards_and_ref_properties() -> None:
    """Contract definitions reject invalid metadata and expose stable ref properties."""
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
    """Registry validation detects duplicate, missing, and unknown usecase bindings."""
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
    """Handler validation rejects invalid async, annotation, callable, and output shapes."""

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
    """Caller records, gather behavior, and strict error policy are enforced."""
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


def test_manifest_docs_graph_and_diff_cover_contract_catalog() -> None:
    """Manifest docs, graph, and diffs cover contract catalog metadata."""
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: GoodImpl(), uses=(EMPTY,))
    api.bind(EMPTY, lambda caller: EmptyImpl())
    manifest = manifest_from_api(api)

    markdown = render_manifest_markdown(manifest)
    assert "Example contract." in markdown
    assert "KnownExampleError" in markdown
    assert "`empty.run@v1`" in markdown

    graph = render_manifest_graph(manifest)
    assert "uc_example_run_v1 --> uc_empty_run_v1" in graph

    changed = deepcopy(manifest)
    changed["usecases"] = [item for item in changed["usecases"] if item["key"] != "empty.run@v1"]
    changed["usecases"][0]["input"] = "DifferentInput"
    changed["usecases"][0]["models"].append({"name": "DifferentInput", "fields": []})
    changed["usecases"][0]["raises"] = []
    changed["usecases"][0]["uses"] = []
    changed["usecases"][0]["deprecated"] = True
    added = deepcopy(changed["usecases"][0])
    added["name"] = "added.run"
    added["namespace"] = "added"
    added["version"] = 1
    added["key"] = "added.run@v1"
    added["source"]["contract_module"] = "app.contracts.added.run.v1"
    added["source"]["protocol_class"] = "AddedRun"
    added["source"]["ref"] = "ADDED_RUN"
    changed["usecases"].append(added)

    diff = diff_manifests(manifest, changed)
    assert diff.breaking == (
        "removed usecase empty.run@v1",
        "changed input model for example.run@v1",
        "removed declared errors for example.run@v1: ExampleError",
    )
    assert diff.warnings == (
        "removed declared uses for example.run@v1: empty.run@v1",
        "deprecated usecase example.run@v1",
    )
    assert diff.additions == ("added usecase added.run@v1",)
    assert diff.to_dict()["breaking"] == list(diff.breaking)
    assert ManifestDiff((), (), ()).has_breaking_changes is False
    assert diff_manifests(manifest, manifest) == ManifestDiff((), (), ())


def test_scaffold_boundaries_and_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scaffold validates boundary cases and does not write files in dry-run mode."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="version"):
        scaffold_usecase(ScaffoldOptions(name="commerce.create", version=0))
    with pytest.raises(ValueError, match="version and next"):
        scaffold_usecase(ScaffoldOptions(name="commerce.create", version=1, next=True))
    with pytest.raises(ValueError, match=r"package\.use_case"):
        scaffold_usecase(ScaffoldOptions(name="commerce"))
    with pytest.raises(ValueError, match="no existing versions"):
        scaffold_usecase(ScaffoldOptions(name="commerce.create", next=True))

    missing_contract = tmp_path / "commerce/usecases/missing/v1"
    missing_contract.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="previous contract file"):
        scaffold_usecase(ScaffoldOptions(name="commerce.missing", next=True))

    previous = tmp_path / "commerce/usecases/create/v1/create_contract.py"
    previous.parent.mkdir(parents=True)
    previous.write_text("VERSION = 1\n")
    with pytest.raises(ValueError, match="could not find version=1"):
        scaffold_usecase(
            ScaffoldOptions(
                name="commerce.create",
                next=True,
            )
        )

    result = scaffold_usecase(
        ScaffoldOptions(
            name="commerce.reserve",
            dry_run=True,
        )
    )
    assert result.version == 1
    assert result.files == (
        Path("commerce/usecases/reserve/v1/reserve_contract.py"),
        Path("commerce/usecases/reserve/v1/reserve_usecase.py"),
        Path("tests/commerce/usecases/reserve/v1/test_reserve.py"),
    )
    assert not (tmp_path / "commerce/usecases/reserve").exists()

    created = scaffold_usecase(
        ScaffoldOptions(
            name="commerce.reserve",
        )
    )
    with pytest.raises(FileExistsError):
        scaffold_usecase(
            ScaffoldOptions(
                name="commerce.reserve",
                version=1,
            )
        )
    assert created.files[0].exists()


def test_cli_commands_validate_service_surface(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI commands inspect, document, diff, and scaffold a service surface."""
    example_root = Path(__file__).parents[1] / "examples" / "basic" / "src"
    sys.path.insert(0, str(example_root))
    try:
        assert main(["check", "composition:usecases"]) == 0
        assert "UseCaseAPI check passed" in capsys.readouterr().out

        assert main(["inspect", "composition:usecases"]) == 0
        inspect_output = yaml.safe_load(capsys.readouterr().out)
        assert {item["key"] for item in inspect_output["usecases"]} == {
            "commerce.check_availability@v1",
            "commerce.checkout@v1",
            "commerce.place_order@v1",
        }

        docs_path = tmp_path / "docs.md"
        graph_path = tmp_path / "graph.mmd"
        manifest_path = tmp_path / "usecaseapi.ucase.yaml"
        assert main(["manifest", "export", "composition:usecases", "-o", str(manifest_path)]) == 0
        assert main(["docs", str(manifest_path), "--output", str(docs_path)]) == 0
        assert main(["graph", str(manifest_path), "-o", str(graph_path)]) == 0
        assert "commerce.checkout v1" in docs_path.read_text()
        assert "commerce.place_order@v1" in graph_path.read_text()
        assert load_manifest(manifest_path)["kind"] == "usecaseapi.manifest/v1"

        monkeypatch.chdir(tmp_path)
        assert (
            main(
                [
                    "scaffold",
                    "billing",
                    "capture_payment",
                ]
            )
            == 0
        )
        scaffold_output = capsys.readouterr().out
        assert "scaffolded version: v1" in scaffold_output
        assert "billing/usecases/capture_payment/v1/capture_payment_contract.py" in scaffold_output
        assert "capture_payment/v1/capture_payment_usecase.py" in scaffold_output

        assert (
            main(
                [
                    "scaffold",
                    "billing",
                    "capture_payment",
                    "--next",
                ]
            )
            == 0
        )
        assert (
            "billing/usecases/capture_payment/v2/capture_payment_contract.py"
            in capsys.readouterr().out
        )

        assert main(["diff", str(manifest_path), str(manifest_path)]) == 0
        assert "Breaking:\n  - none" in capsys.readouterr().out
        assert main(["diff", str(manifest_path), str(manifest_path), "--json"]) == 0
        assert json.loads(capsys.readouterr().out) == {
            "breaking": [],
            "warnings": [],
            "additions": [],
        }

        changed_path = tmp_path / "changed.ucase.yaml"
        changed = load_manifest(manifest_path)
        changed["usecases"] = changed["usecases"][1:]
        changed_path.write_text(yaml.safe_dump(changed, sort_keys=False))
        assert main(["diff", str(manifest_path), str(changed_path)]) == 1
        assert "removed usecase" in capsys.readouterr().out

        assert main(["manifest", "export", "composition:usecases"]) == 0
        assert "commerce.checkout@v1" in capsys.readouterr().out
    finally:
        sys.path.remove(str(example_root))


def test_cli_import_path_errors_and_main_module(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI reports invalid import paths and supports module execution."""
    import typer

    import usecaseapi.cli as cli

    assert isinstance(cli.app, typer.Typer)

    with pytest.raises(ValueError, match="module:attribute"):
        main(["check", "not-an-import-path"])
    with pytest.raises(TypeError, match="UseCaseAPI"):
        main(["check", "json:loads"])

    assert main([]) == 0
    assert "Usage:" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["usecaseapi", "--help"])
    sys.modules.pop("usecaseapi.cli", None)
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("usecaseapi.cli", run_name="__main__")
    assert exc_info.value.code == 0


def test_cli_scaffold_argument_error_and_main_exit_handling(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI reports scaffold argument errors and preserves Typer exit codes."""
    import click

    assert main(["scaffold", "billing", "capture_payment", "--version", "1", "--next"]) == 2
    assert "version and --next cannot be used together" in capsys.readouterr().err

    assert main(["scaffold", "billing"]) == 2
    assert "Missing argument" in capsys.readouterr().err

    monkeypatch.setitem(
        main.__globals__,
        "scaffold_usecase",
        lambda options: ScaffoldResult(
            files=(Path("created.py"),),
            version=1,
        ),
    )

    assert main(["scaffold", "billing", "capture_payment"]) == 0
    output = capsys.readouterr().out
    assert "created: created.py" in output

    monkeypatch.setitem(main.__globals__, "app", lambda **kwargs: 7)
    assert main(["anything"]) == 7

    def raise_exit(**kwargs: object) -> int:
        raise click.exceptions.Exit(5)

    monkeypatch.setitem(main.__globals__, "app", raise_exit)
    assert main(["anything"]) == 5

    def raise_click_exception(**kwargs: object) -> int:
        raise click.UsageError("invalid command usage")

    monkeypatch.setitem(main.__globals__, "app", raise_click_exception)
    assert main(["anything"]) == 2
    assert "invalid command usage" in capsys.readouterr().err


def test_usecase_error_serialization() -> None:
    """UseCaseError serializes code, message, type, and public details."""
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
