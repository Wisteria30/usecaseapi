"""Manifest catalog behavior tests."""

from __future__ import annotations

import ast
import inspect
import json

from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol, cast, get_type_hints
from uuid import UUID

import pytest
import yaml

from pydantic import Field

import usecaseapi.manifest as manifest_module

from usecaseapi import (
    Contract,
    Model,
    UseCase,
    UseCaseAPI,
    UseCaseError,
    UseCaseRef,
    define_usecase,
)
from usecaseapi.cli import main
from usecaseapi.manifest import (
    ManifestError,
    diff_manifests,
    dump_manifest,
    guard_manifests,
    load_manifest,
    manifest_from_api,
    render_contract_module,
    render_manifest_graph,
    render_manifest_markdown,
    scaffold_from_manifest,
    validate_manifest,
)


class Input(Model):
    """Input for the manifest example."""

    value: int


class Output(Model):
    """Output for the manifest example."""

    value: int


class ExampleError(UseCaseError):
    """Base example error."""

    code = "example.run"


class ExampleRejected(ExampleError):
    """Specific example error."""

    code = "example.run.rejected"

    def __init__(self, *, reason: str) -> None:
        """Create a rejected example error."""
        self.reason = reason
        super().__init__(reason)


class Example(UseCase[Input, Output], Protocol):
    """Example usecase protocol."""

    async def __call__(self, input: Input, /) -> Output:
        """Run the example."""
        ...


EXAMPLE: UseCaseRef[Input, Output] = define_usecase(
    Example,
    Contract(
        name="example.run",
        version=1,
        input=Input,
        output=Output,
        raises=(ExampleError,),
        known_errors=(ExampleRejected,),
        description="Run an example usecase.",
        tags=("examples",),
    ),
)


class ExampleImpl:
    """Example implementation."""

    async def __call__(self, input: Input, /) -> Output:
        """Return the input value."""
        return Output(value=input.value)


class RichNested(Model):
    """Nested rich input model."""

    label: str


class RichInput(Model):
    """Input with annotations used by Manifest rendering."""

    anything: Any = Field(description="Open value")
    nested: RichNested
    maybe_nested: RichNested | None = None
    items: list[RichNested]
    lookup: dict[str, Any]
    unique_ids: set[UUID]
    pair: tuple[date, datetime]
    amount: Decimal
    status: Literal["accepted"]


class RichOutput(Model):
    """Rich output model."""

    result: str


class RichError(UseCaseError):
    """Error with annotated fields."""

    code: ClassVar[str] = "rich.run"
    reason: str


class Rich(UseCase[RichInput, RichOutput], Protocol):
    """Rich protocol."""

    async def __call__(self, input: RichInput, /) -> RichOutput:
        """Run the rich usecase."""
        ...


RICH: UseCaseRef[RichInput, RichOutput] = define_usecase(
    Rich,
    Contract(
        name="rich.run",
        version=1,
        input=RichInput,
        output=RichOutput,
        raises=(RichError,),
        known_errors=(RichError,),
        superseded_by="rich.run@v2",
    ),
)


class RichImpl:
    """Rich implementation."""

    async def __call__(self, input: RichInput, /) -> RichOutput:
        """Return a rich result."""
        return RichOutput(result=input.status)


def minimal_manifest() -> dict[str, Any]:
    """Create a minimal valid Manifest mapping."""
    return {
        "kind": manifest_module.LEGACY_MANIFEST_KIND,
        "usecases": [
            {
                "name": "example.run",
                "version": 1,
                "source": {
                    "contract_module": "app.contracts.example.run.v1",
                    "protocol_class": "Example",
                    "ref": "EXAMPLE",
                },
                "input": "Input",
                "output": "Output",
                "models": [
                    {"name": "Input", "fields": []},
                    {"name": "Output", "fields": []},
                ],
                "errors": [],
                "raises": [],
                "known_errors": [],
                "uses": [],
            }
        ],
    }


def test_manifest_export_is_yaml_and_validates(tmp_path: Path) -> None:
    """Exported manifests are YAML catalogs that validate."""
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: ExampleImpl())

    manifest = manifest_from_api(
        api,
        project="demo",
        package="example",
        implementations_root="src",
    )
    path = tmp_path / "usecaseapi.yaml"
    dump_manifest(manifest, path)
    loaded = load_manifest(path)
    semantic = manifest_module.semantic_from_openapi_manifest(loaded)
    usecase = semantic["usecases"][0]

    assert loaded["openapi"] == "3.1.0"
    assert loaded["x-usecaseapi"]["manifestKind"] == "usecaseapi.openapi.profile/3.1.0"
    assert semantic["metadata"]["name"] == "demo"
    assert semantic["layout"]["package"] == "example"
    assert semantic["layout"]["implementations_root"] == "src"
    assert usecase["key"] == "example.run@v1"
    assert usecase["models"][0]["description"] == "Input for the manifest example."
    assert usecase["source"]["implementation_class"] == "RunUseCase"
    assert usecase["source"]["implementation_file"] == (
        "src/example/usecases/run/v1/run_usecase.py"
    )
    assert usecase["raises"] == ["ExampleError"]
    assert usecase["known_errors"] == ["ExampleRejected"]


def test_manifest_export_includes_binding_metadata_and_rich_types() -> None:
    """Export includes binding metadata, schemas, and rich annotation rendering."""
    api = UseCaseAPI[None]()
    api.bind(
        RICH,
        lambda caller: RichImpl(),
        description="Factory description.",
        tags=("factory",),
    )

    manifest = manifest_from_api(
        api,
        project="rich",
        include_json_schema=True,
        contracts_root="not/a/matching/root",
    )
    usecase = manifest_module.usecase_items(manifest)[0]
    contract = render_contract_module(usecase)

    operation = manifest["paths"]["/_usecases/rich.run/v1/call"]["post"]
    assert operation["tags"] == ["factory"]
    assert manifest["components"]["schemas"]["RichRunV1RichInput"]["title"] == "RichInput"
    assert "description: Open value" in yaml.safe_dump(usecase)
    assert "from uuid import UUID" in contract
    assert "from datetime import date, datetime" in contract
    assert "from decimal import Decimal" in contract
    assert "anything: Any" in contract
    assert "maybe_nested: RichNested | None = None" in contract
    assert "unique_ids: set[UUID]" in contract
    assert "pair: tuple[date, datetime]" in contract
    assert "superseded_by='rich.run@v2'" in contract


def test_manifest_validation_rejects_unsafe_type_expression() -> None:
    """Manifest type expressions are a small annotation subset."""
    manifest = {
        "kind": manifest_module.LEGACY_MANIFEST_KIND,
        "usecases": [
            {
                "name": "example.run",
                "version": 1,
                "source": {
                    "contract_module": "app.contracts.example.run.v1",
                    "protocol_class": "Example",
                    "ref": "EXAMPLE",
                },
                "input": "Input",
                "output": "Output",
                "models": [
                    {
                        "name": "Input",
                        "fields": [{"name": "value", "type": "call_me()", "required": True}],
                    },
                    {"name": "Output", "fields": []},
                ],
                "errors": [],
                "raises": [],
                "known_errors": [],
                "uses": [],
            }
        ],
    }

    with pytest.raises(ManifestError, match="unsupported type expression"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda manifest: manifest.update({"kind": "bad"}), "manifest kind"),
        (lambda manifest: manifest.update({"usecases": []}), "non-empty list"),
        (lambda manifest: manifest.update({"usecases": [None]}), "usecases\\[0\\]"),
        (
            lambda manifest: manifest["usecases"][0].update({"name": "Example"}),
            "name must look",
        ),
        (
            lambda manifest: manifest["usecases"][0].update({"domain": "example"}),
            "domain is not supported",
        ),
        (lambda manifest: manifest["usecases"][0].update({"version": 0}), "version must be"),
        (lambda manifest: manifest["usecases"][0].update({"version": "1"}), "version must be"),
        (lambda manifest: manifest["usecases"][0].update({"key": "wrong@v1"}), "key must be"),
        (
            lambda manifest: manifest.update(
                {"usecases": [manifest["usecases"][0], manifest["usecases"][0]]}
            ),
            "duplicate usecase key",
        ),
        (
            lambda manifest: manifest["usecases"][0]["source"].update(
                {"contract_module": "bad-module"}
            ),
            "contract_module is invalid",
        ),
        (
            lambda manifest: manifest["usecases"][0]["source"].update(
                {"protocol_class": "bad-name"}
            ),
            "protocol_class must be an identifier",
        ),
        (lambda manifest: manifest["usecases"][0].update({"input": "bad-name"}), "input/output"),
        (
            lambda manifest: manifest["usecases"][0]["models"][0].update({"name": "bad-name"}),
            "model name",
        ),
        (
            lambda manifest: manifest["usecases"][0]["models"].append(
                {"name": "Input", "fields": []}
            ),
            "duplicate model name",
        ),
        (lambda manifest: manifest["usecases"][0].update({"input": "Missing"}), "input model"),
        (lambda manifest: manifest["usecases"][0].update({"output": "Missing"}), "output model"),
        (
            lambda manifest: manifest["usecases"][0]["models"][0].update(
                {"fields": [{"name": "bad-name", "type": "str"}]}
            ),
            "field name",
        ),
        (
            lambda manifest: manifest["usecases"][0]["models"][0].update(
                {"fields": [{"name": "value", "type": "str", "required": "yes"}]}
            ),
            "required must be a boolean",
        ),
        (lambda manifest: manifest["usecases"][0].update({"models": []}), "models"),
        (lambda manifest: manifest["usecases"][0].update({"errors": {}}), "errors"),
        (lambda manifest: manifest["usecases"][0]["models"][0].update({"fields": {}}), "fields"),
        (lambda manifest: manifest.update({"usecases": {}}), "manifest.usecases"),
        (
            lambda manifest: manifest["usecases"][0].update(
                {"uses": ["bad"], "errors": [], "raises": [], "known_errors": []}
            ),
            "invalid uses key",
        ),
        (
            lambda manifest: manifest["usecases"][0].update({"uses": ["example.run@v1"]}),
            "cannot use itself",
        ),
        (lambda manifest: manifest["usecases"][0].update({"raises": "Error"}), "expected a list"),
        (lambda manifest: manifest["usecases"][0].update({"raises": [1]}), "expected a list"),
    ],
)
def test_manifest_validation_rejects_invalid_catalog_shapes(
    mutate: Callable[[dict[str, Any]], None],
    message: str,
    tmp_path: Path,
) -> None:
    """Validation rejects malformed Manifest shapes and references."""
    manifest = minimal_manifest()
    mutate(manifest)

    with pytest.raises(ManifestError, match=message):
        validate_manifest(manifest)

    invalid_path = tmp_path / "invalid.yaml"
    invalid_path.write_text("- not: a mapping\n")
    with pytest.raises(ManifestError, match="YAML mapping"):
        load_manifest(invalid_path)


def test_manifest_validation_checks_error_boundaries() -> None:
    """Known errors must be defined and covered by a declared raise boundary."""
    manifest = {
        "kind": manifest_module.LEGACY_MANIFEST_KIND,
        "usecases": [
            {
                "name": "example.run",
                "version": 1,
                "source": {
                    "contract_module": "app.contracts.example.run.v1",
                    "protocol_class": "Example",
                    "ref": "EXAMPLE",
                },
                "input": "Input",
                "output": "Output",
                "models": [
                    {"name": "Input", "fields": []},
                    {"name": "Output", "fields": []},
                ],
                "errors": [
                    {"name": "OtherError", "base": "UseCaseError", "code": "other"},
                    {
                        "name": "ExampleRejected",
                        "base": "ExampleError",
                        "code": "example.run.rejected",
                    },
                ],
                "raises": ["OtherError"],
                "known_errors": ["ExampleRejected"],
                "uses": [],
            }
        ],
    }

    with pytest.raises(ManifestError, match="extends unknown base"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("errors", "raises", "known_errors", "message"),
    [
        ([{"name": "Bad-Error", "base": "UseCaseError", "code": "bad"}], [], [], "error name"),
        (
            [{"name": "ExampleError", "base": "UseCaseError", "code": "example"}],
            ["MissingError"],
            [],
            "declared error",
        ),
        (
            [
                {"name": "OtherError", "base": "UseCaseError", "code": "other"},
                {"name": "ExampleError", "base": "UseCaseError", "code": "example"},
                {"name": "ExampleRejected", "base": "ExampleError", "code": "example.rejected"},
            ],
            ["OtherError"],
            ["ExampleRejected"],
            "covered by raises",
        ),
        (
            [
                {"name": "ExampleError", "base": "UseCaseError", "code": "example"},
                {"name": "ExampleError", "base": "UseCaseError", "code": "example"},
            ],
            [],
            [],
            "duplicate error name",
        ),
    ],
)
def test_manifest_validation_rejects_error_declaration_issues(
    errors: list[dict[str, Any]],
    raises: list[str],
    known_errors: list[str],
    message: str,
) -> None:
    """Validation rejects invalid domain error declarations."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["errors"] = errors
    manifest["usecases"][0]["raises"] = raises
    manifest["usecases"][0]["known_errors"] = known_errors

    with pytest.raises(ManifestError, match=message):
        validate_manifest(manifest)


def test_manifest_scaffold_generates_contract_and_implementation(tmp_path: Path) -> None:
    """Manifest scaffold generates server-side Python skeletons."""
    manifest = yaml.safe_load(
        """
kind: usecaseapi.manifest/v1
metadata:
  name: demo
runtime:
  language: python
  python: '>=3.12,<3.15'
  protocol: usecaseapi.inprocess.async_call/v1
layout:
  contracts_root: app/contracts
  implementations_root: app/usecases
usecases:
  - name: orders.place_order
    version: 1
    key: orders.place_order@v1
    description: Place an order.
    stable: true
    deprecated: false
    protocol:
      kind: usecaseapi.inprocess.async_call/v1
      signature: 'async __call__(input: Input) -> Output'
    source:
      contract_file: app/contracts/orders/place_order/v1.py
      implementation_file: app/usecases/orders/place_order.py
      contract_module: app.contracts.orders.place_order.v1
      protocol_class: PlaceOrder
      implementation_class: PlaceOrderImpl
      ref: PLACE_ORDER
    input: Input
    output: Output
    models:
      - name: Item
        fields:
          - name: sku_id
            type: str
            required: true
          - name: quantity
            type: int
            required: true
      - name: Input
        fields:
          - name: user_id
            type: str
            required: true
          - name: item
            type: Item
            required: true
      - name: Output
        fields:
          - name: order_id
            type: str
            required: true
    errors:
      - name: PlaceOrderError
        base: UseCaseError
        code: orders.place_order
        fields: []
      - name: InventoryShortage
        base: PlaceOrderError
        code: orders.place_order.inventory_shortage
        fields:
          - name: sku_id
            type: str
            required: true
          - name: requested
            type: int
            required: true
          - name: available
            type: int
            required: true
    raises:
      - PlaceOrderError
    known_errors:
      - InventoryShortage
    uses: []
"""
    )

    result = scaffold_from_manifest(manifest, root=tmp_path)

    contract_file = tmp_path / "app/contracts/orders/place_order/v1.py"
    implementation_file = tmp_path / "app/usecases/orders/place_order.py"
    test_file = tmp_path / "tests/orders/place_order/v1/test_place_order.py"
    assert contract_file in result.files
    assert implementation_file in result.files
    assert test_file in result.files
    assert "class PlaceOrder(UseCase[Input, Output], Protocol):" in contract_file.read_text()
    assert "class InventoryShortage(PlaceOrderError):" in contract_file.read_text()
    assert "PLACE_ORDER: UseCaseRef[Input, Output]" in contract_file.read_text()
    implementation_text = implementation_file.read_text()
    assert "_impl" not in implementation_text
    test_text = test_file.read_text()
    assert "from app.contracts.orders.place_order.v1 import (" in test_text
    assert "from app.usecases.orders.place_order import (\n    PlaceOrderImpl,\n)" in test_text
    assert "usecase: PlaceOrder = PlaceOrderImpl()" in test_text


def test_manifest_scaffold_handles_dry_run_existing_files_and_default_paths(
    tmp_path: Path,
) -> None:
    """Manifest scaffold supports dry-run, skipped implementations, and default file paths."""
    manifest = minimal_manifest()
    source = manifest["usecases"][0]["source"]
    source.pop("contract_file", None)
    source.pop("implementation_file", None)

    dry_result = scaffold_from_manifest(
        manifest,
        root=tmp_path,
        dry_run=True,
        create_implementation=False,
    )
    assert dry_result.files == (tmp_path / "app/contracts/example/run/v1.py",)
    assert not dry_result.files[0].exists()

    first = scaffold_from_manifest(manifest, root=tmp_path)
    second = scaffold_from_manifest(manifest, root=tmp_path, force=True)
    (tmp_path / "app/contracts/example/run/v1.py").unlink()
    third = scaffold_from_manifest(manifest, root=tmp_path)

    assert tmp_path / "app/contracts/example/run/v1.py" in first.files
    assert tmp_path / "app/usecases/example/run.py" in second.files
    assert third.skipped == (
        tmp_path / "app/usecases/example/run.py",
        tmp_path / "tests/example/run/v1/test_run.py",
    )

    with pytest.raises(FileExistsError, match="already exists"):
        scaffold_from_manifest(manifest, root=tmp_path, create_implementation=False)

    v2_manifest = deepcopy(manifest)
    v2_manifest["layout"] = {
        "contracts_root": "src/contracts",
        "implementations_root": "src/usecases",
        "tests_root": "specs",
        "package": "app",
    }
    v2_openapi_manifest = manifest_module.openapi_manifest_from_semantic(v2_manifest)
    v2_result = scaffold_from_manifest(
        v2_openapi_manifest,
        root=tmp_path / "v2",
        dry_run=True,
    )
    assert tmp_path / "v2/src/contracts/example/run/v1.py" in v2_result.files
    assert tmp_path / "v2/src/usecases/example/run.py" in v2_result.files
    assert tmp_path / "v2/specs/example/run/v1/test_run.py" in v2_result.files


def test_manifest_renders_docs_graph_and_diff() -> None:
    """Docs, graph, and diff are derived from Manifest YAML data."""
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: ExampleImpl())
    manifest = manifest_from_api(api, project="demo")

    markdown = render_manifest_markdown(manifest)
    graph = render_manifest_graph(manifest)
    changed = manifest_module.semantic_from_openapi_manifest(
        yaml.safe_load(yaml.safe_dump(manifest))
    )
    changed["usecases"][0]["output"] = "DifferentOutput"
    changed["usecases"][0]["models"].append({"name": "DifferentOutput", "fields": []})
    diff = diff_manifests(manifest, changed)

    assert "example.run v1" in markdown
    assert "### Models" in markdown
    assert "Input for the manifest example." in markdown
    assert "| `value` | `int` | yes |" in markdown
    assert "### Errors" in markdown
    assert "| `ExampleRejected` | `ExampleError` | `example.run.rejected` |" in markdown
    assert "Specific example error." in markdown
    assert "### Source" in markdown
    assert "`contract_module`: `test_manifest`" in markdown
    assert "ExampleRejected" in markdown
    assert "example.run@v1" in graph
    assert diff.has_breaking_changes
    assert diff.breaking == ("changed output model for example.run@v1",)


def test_manifest_diff_reports_model_errors_and_removed_values() -> None:
    """Manifest diff reports field, error, raise, use, and deprecation changes."""
    old = minimal_manifest()
    old_case = old["usecases"][0]
    old_case["errors"] = [{"name": "ExampleError", "base": "UseCaseError", "code": "example"}]
    old_case["raises"] = ["ExampleError"]
    old_case["uses"] = ["other.run@v1"]
    old_case["deprecated"] = False
    new = deepcopy(old)
    new_case = new["usecases"][0]
    new_case["models"][0]["fields"] = [{"name": "value", "type": "str"}]
    new_case["errors"][0]["code"] = "example.changed"
    new_case["raises"] = []
    new_case["uses"] = []
    new_case["deprecated"] = True

    diff = diff_manifests(old, new)

    assert "changed model fields for example.run@v1" in diff.breaking
    assert "changed errors for example.run@v1" in diff.breaking
    assert "removed declared errors for example.run@v1: ExampleError" in diff.breaking
    assert diff.warnings == (
        "removed declared uses for example.run@v1: other.run@v1",
        "deprecated usecase example.run@v1",
    )


def test_manifest_guard_allows_new_usecase_version() -> None:
    """The immutable guard accepts adding a major version with new error metadata."""
    base = load_manifest("examples/basic/usecaseapi.yaml")
    semantic = manifest_module.semantic_from_openapi_manifest(base)
    source_usecase = next(
        usecase for usecase in semantic["usecases"] if usecase["key"] == "commerce.place_order@v1"
    )
    new_usecase = deepcopy(source_usecase)
    new_usecase["version"] = 2
    new_usecase["key"] = str(new_usecase["key"]).replace("@v1", "@v2")
    semantic["usecases"].append(new_usecase)
    head = manifest_module.openapi_manifest_from_semantic(semantic)

    report = guard_manifests(base, head)

    assert report.failed is False
    assert "commerce." in report.added[0]
    assert report.changed == ()
    assert report.removed == ()


def test_manifest_guard_rejects_removed_existing_version() -> None:
    """The immutable guard rejects removing an existing usecase version."""
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = deepcopy(base)
    paths = cast(dict[str, object], head["paths"])
    removed_path = next(iter(paths))
    del paths[removed_path]

    report = guard_manifests(base, head)

    assert report.failed is True
    assert report.removed
    assert report.changed == ()


def test_manifest_guard_rejects_changed_existing_version() -> None:
    """The immutable guard rejects changing an existing usecase version."""
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = deepcopy(base)
    paths = cast(dict[str, object], head["paths"])
    operation = cast(dict[str, object], cast(dict[str, object], next(iter(paths.values())))["post"])
    operation["summary"] = "changed summary"

    report = guard_manifests(base, head)

    assert report.failed is True
    assert report.changed
    assert report.removed == ()


def test_manifest_guard_rejects_changed_referenced_root_error_metadata() -> None:
    """The immutable guard rejects changes to referenced root error metadata."""
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = deepcopy(base)
    root_extension = cast(dict[str, object], head["x-usecaseapi"])
    extension_components = cast(dict[str, object], root_extension["components"])
    errors = cast(dict[str, object], extension_components["errors"])
    error = cast(dict[str, object], errors["CommercePlaceOrderV1InventoryShortage"])
    error["description"] = "Changed referenced root error metadata."

    report = guard_manifests(base, head)

    assert report.failed is True
    assert "commerce.place_order@v1" in report.changed
    assert report.removed == ()


def test_manifest_guard_cli_fails_for_changed_existing_version(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The manifest guard CLI fails when an existing version changes."""
    base_path = tmp_path / "base.yaml"
    head_path = tmp_path / "head.yaml"
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = deepcopy(base)
    paths = cast(dict[str, object], head["paths"])
    operation = cast(dict[str, object], cast(dict[str, object], next(iter(paths.values())))["post"])
    operation["summary"] = "changed summary"
    dump_manifest(base, base_path)
    dump_manifest(head, head_path)

    assert main(["manifest", "guard", str(base_path), str(head_path)]) == 1

    output = capsys.readouterr().out
    assert "Removed:" in output
    assert "Changed:" in output
    assert "Additions:" in output


def test_manifest_guard_cli_passes_for_identical_manifests(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The manifest guard CLI passes and can print JSON for identical manifests."""
    base_path = tmp_path / "base.yaml"
    head_path = tmp_path / "head.yaml"
    manifest = load_manifest("examples/basic/usecaseapi.yaml")
    dump_manifest(manifest, base_path)
    dump_manifest(manifest, head_path)

    assert main(["manifest", "guard", str(base_path), str(head_path)]) == 0
    output = capsys.readouterr().out
    assert "Removed:" in output
    assert "Changed:" in output
    assert "Additions:" in output

    assert main(["manifest", "guard", str(base_path), str(head_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "failed": False,
        "removed": [],
        "changed": [],
        "added": [],
    }


def test_manifest_ci_writes_reports_for_valid_example(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manifest ci command writes Markdown and JSON reports for a valid catalog."""
    summary = tmp_path / "contract-check.md"
    json_report = tmp_path / "contract-check.json"
    monkeypatch.chdir("examples/basic")
    monkeypatch.syspath_prepend("src")

    exit_code = main(
        [
            "manifest",
            "ci",
            "--target",
            "composition:usecases",
            "--manifest",
            "usecaseapi.yaml",
            "--summary",
            str(summary),
            "--json",
            str(json_report),
        ]
    )

    assert exit_code == 0
    stdout = capsys.readouterr().out
    markdown = summary.read_text()
    report = json.loads(json_report.read_text())
    assert "<!-- usecaseapi-contract-check -->" in stdout
    assert "Status: Passed" in markdown
    assert "Manifest: `usecaseapi.yaml`" in markdown
    assert "Target: `composition:usecases`" in markdown
    assert report["status"] == "passed"
    assert report["validation"] == {"manifest": "passed", "sync": "passed"}


def test_manifest_ci_fails_when_base_contract_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manifest ci command fails when an existing base contract changes."""
    base_path = tmp_path / "base.yaml"
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = deepcopy(base)
    paths = cast(dict[str, object], base["paths"])
    operation = cast(dict[str, object], cast(dict[str, object], next(iter(paths.values())))["post"])
    operation["summary"] = "old summary"
    dump_manifest(base, base_path)
    head_path = tmp_path / "usecaseapi.yaml"
    dump_manifest(head, head_path)
    monkeypatch.chdir("examples/basic")
    monkeypatch.syspath_prepend("src")

    exit_code = main(
        [
            "manifest",
            "ci",
            "--target",
            "composition:usecases",
            "--manifest",
            str(head_path),
            "--base-manifest",
            str(base_path),
        ]
    )

    assert exit_code == 1


def test_manifest_ci_fails_when_manifest_is_not_synchronized(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manifest ci command fails when committed YAML differs from target code."""
    changed = manifest_module.semantic_from_openapi_manifest(
        load_manifest("examples/basic/usecaseapi.yaml")
    )
    changed["usecases"][0]["output"] = "DifferentOutput"
    changed["usecases"][0]["models"].append({"name": "DifferentOutput", "fields": []})
    changed_path = tmp_path / "changed.yaml"
    changed_path.write_text(yaml.safe_dump(changed, sort_keys=False))
    monkeypatch.chdir("examples/basic")
    monkeypatch.syspath_prepend("src")

    exit_code = main(
        [
            "manifest",
            "ci",
            "--target",
            "composition:usecases",
            "--manifest",
            str(changed_path),
        ]
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "Status: Failed" in output
    assert "breaking: changed output model" in output


def test_manifest_ci_reports_missing_manifest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manifest ci command reports a missing manifest without an unhandled traceback."""
    summary = tmp_path / "contract-check.md"
    missing = tmp_path / "missing.yaml"
    monkeypatch.chdir("examples/basic")
    monkeypatch.syspath_prepend("src")

    exit_code = main(
        [
            "manifest",
            "ci",
            "--target",
            "composition:usecases",
            "--manifest",
            str(missing),
            "--summary",
            str(summary),
        ]
    )

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "Status: Failed" in output
    assert str(missing) in summary.read_text()


def test_manifest_ci_reports_invalid_yaml_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manifest ci command writes reports when YAML parsing fails."""
    bad_manifest = tmp_path / "bad.yaml"
    summary = tmp_path / "contract-check.md"
    json_path = tmp_path / "contract-check.json"
    bad_manifest.write_text("openapi: [unterminated\n")
    monkeypatch.chdir("examples/basic")
    monkeypatch.syspath_prepend("src")

    exit_code = main(
        [
            "manifest",
            "ci",
            "--target",
            "composition:usecases",
            "--manifest",
            str(bad_manifest),
            "--summary",
            str(summary),
            "--json",
            str(json_path),
        ]
    )

    assert exit_code == 1
    markdown = summary.read_text()
    report = json.loads(json_path.read_text())
    assert "Status: Failed" in markdown
    assert report["status"] == "failed"
    assert report["errors"]
    assert "manifest validation failed" in report["errors"][0]


def test_manifest_cli_uses_yaml_for_export_validate_scaffold_docs_graph_and_diff(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI uses Manifest YAML as the catalog for all catalog commands."""
    monkeypatch.syspath_prepend("examples/basic/src")
    manifest_path = tmp_path / "usecaseapi.yaml"
    docs_path = tmp_path / "docs.md"
    graph_path = tmp_path / "graph.mmd"

    assert (
        main(
            [
                "manifest",
                "export",
                "composition:usecases",
                "--output",
                str(manifest_path),
            ]
        )
        == 0
    )
    manifest = load_manifest(manifest_path)
    assert manifest["openapi"] == "3.1.0"
    semantic = manifest_module.semantic_from_openapi_manifest(manifest)
    assert semantic["usecases"][0]["source"]["implementation_file"] == (
        "src/commerce/usecases/check_availability/v1/check_availability_usecase.py"
    )

    assert main(["manifest", "validate", str(manifest_path)]) == 0
    assert "UseCaseAPI manifest validation passed" in capsys.readouterr().out

    assert main(["manifest", "check-sync", "composition:usecases", str(manifest_path)]) == 0
    assert "UseCaseAPI manifest is synchronized" in capsys.readouterr().out

    generated_root = tmp_path / "generated"
    assert main(["manifest", "scaffold", str(manifest_path), "--root", str(generated_root)]) == 0
    assert (
        generated_root / "src/commerce/usecases/place_order/v1/place_order_contract.py"
    ).exists()

    assert main(["docs", str(manifest_path), "--output", str(docs_path)]) == 0
    assert "commerce.place_order v1" in docs_path.read_text()

    assert main(["graph", str(manifest_path), "-o", str(graph_path)]) == 0
    assert "commerce.place_order@v1" in graph_path.read_text()

    assert main(["diff", str(manifest_path), str(manifest_path)]) == 0

    assert main(["manifest", "export", "composition:usecases"]) == 0
    stdout_manifest = yaml.safe_load(capsys.readouterr().out)
    assert stdout_manifest["openapi"] == "3.1.0"


def test_basic_example_manifest_is_generated_from_composition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The committed basic example Manifest matches CLI export output."""
    monkeypatch.chdir("examples/basic")
    monkeypatch.syspath_prepend("src")
    exported_path = tmp_path / "usecaseapi.yaml"
    committed_path = Path("usecaseapi.yaml")

    assert (
        main(
            [
                "manifest",
                "export",
                "composition:usecases",
                "--output",
                str(exported_path),
            ]
        )
        == 0
    )

    assert load_manifest(committed_path) == load_manifest(exported_path)

    generated_root = tmp_path / "generated"
    assert main(["manifest", "scaffold", str(committed_path), "--root", str(generated_root)]) == 0
    generated_contract = (
        generated_root / "src/commerce/usecases/place_order/v1/place_order_contract.py"
    )
    generated_usecase = (
        generated_root / "src/commerce/usecases/place_order/v1/place_order_usecase.py"
    )
    assert generated_contract.exists()
    contract_text = generated_contract.read_text()
    usecase_text = generated_usecase.read_text()
    assert contract_text.startswith('"""Creates an order after inventory has been confirmed."""')
    assert '"""Input required to place an order."""' in contract_text
    assert '"""Accepted order result."""' in contract_text
    assert usecase_text.startswith('"""Creates an order after inventory has been confirmed."""')
    assert (
        'class PlaceOrderUseCase:\n    """Creates an order after inventory has been confirmed."""'
        in (usecase_text)
    )


def test_manifest_cli_covers_error_and_stdout_branches(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI Manifest commands cover non-default branches and mismatch output."""
    monkeypatch.syspath_prepend("examples/basic/src")
    manifest_path = tmp_path / "usecaseapi.yaml"
    docs_path = tmp_path / "docs.md"

    assert main(["manifest", "export", "composition:usecases", "-o", str(manifest_path)]) == 0
    assert main(["docs", str(manifest_path)]) == 0
    assert "commerce.checkout v1" in capsys.readouterr().out
    assert main(["graph", str(manifest_path)]) == 0
    assert "commerce.checkout@v1" in capsys.readouterr().out

    assert (
        main(
            [
                "manifest",
                "scaffold",
                str(manifest_path),
                "--root",
                str(tmp_path / "dry"),
                "--dry-run",
            ]
        )
        == 0
    )
    assert "created:" in capsys.readouterr().out

    changed = manifest_module.semantic_from_openapi_manifest(load_manifest(manifest_path))
    changed["usecases"][0]["output"] = "DifferentOutput"
    changed["usecases"][0]["models"].append({"name": "DifferentOutput", "fields": []})
    changed_path = tmp_path / "changed.yaml"
    changed_path.write_text(yaml.safe_dump(changed, sort_keys=False))
    assert main(["manifest", "check-sync", "composition:usecases", str(changed_path)]) == 1
    assert "Breaking:" in capsys.readouterr().out

    assert main(["docs", str(manifest_path), "-o", str(docs_path)]) == 0
    assert docs_path.exists()

    assert main(["manifest", "unknown"]) == 2

    assert main(["diff", str(changed_path), str(manifest_path)]) == 1


def test_manifest_cli_prints_skipped_scaffold_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI scaffold reports skipped implementation files."""
    manifest = minimal_manifest()
    manifest_path = tmp_path / "usecaseapi.yaml"
    dump_manifest(manifest, manifest_path)
    implementation = tmp_path / "app/usecases/example/run.py"
    implementation.parent.mkdir(parents=True)
    implementation.write_text("# existing\n")

    assert main(["manifest", "scaffold", str(manifest_path), "--root", str(tmp_path)]) == 0

    assert f"skipped: {implementation}" in capsys.readouterr().out


def test_manifest_named_helpers_cover_edge_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Helper edge cases stay explicit for full line coverage."""

    class AnnotatedError(UseCaseError):
        code: ClassVar[str] = "annotated"
        detail: str

    class VariadicError(UseCaseError):
        code: ClassVar[str] = "variadic"

        def __init__(self, *values: str) -> None:
            super().__init__(",".join(values))

    class UnannotatedError(UseCaseError):
        code: ClassVar[str] = "unannotated"

        def __init__(self, reason) -> None:  # type: ignore[no-untyped-def]
            super().__init__(reason)

    original_get_type_hints = get_type_hints

    def failing_class_hints(value: object) -> dict[str, object]:
        if value is AnnotatedError:
            raise NameError("missing")
        return original_get_type_hints(value)

    monkeypatch.setattr(manifest_module, "get_type_hints", failing_class_hints)
    assert manifest_module.error_fields(AnnotatedError) == [
        {"name": "detail", "type": "str", "required": True}
    ]

    original_signature = inspect.signature

    def failing_signature(value: Any) -> object:
        if value is VariadicError.__init__:
            raise ValueError("no signature")
        return original_signature(value)

    monkeypatch.setattr("usecaseapi.manifest.inspect.signature", failing_signature)
    assert manifest_module.error_fields(VariadicError) == []
    monkeypatch.setattr("usecaseapi.manifest.inspect.signature", original_signature)
    assert manifest_module.error_fields(VariadicError) == []
    assert manifest_module.error_fields(UnannotatedError) == []

    assert manifest_module.format_origin_annotation(tuple, tuple[()]) == "<class 'tuple'>"
    assert manifest_module.format_collection_annotation(list, ()) == "<class 'list'>"
    assert manifest_module.format_origin_annotation(object, object()).startswith("<object object")
    assert manifest_module.type_expr_contains_name("[", "Any") is False

    bad_name = ast.Name(id="bad-name")
    with pytest.raises(ManifestError, match="invalid type name"):
        manifest_module.validate_type_ast(bad_name, expr="bad-name")
    with pytest.raises(ManifestError, match="invalid type expression"):
        manifest_module.validate_type_expr("[")
    with pytest.raises(ManifestError, match="invalid literal"):
        manifest_module.validate_type_expr("b'bytes'")
    with pytest.raises(ManifestError, match="manifest.usecases"):
        manifest_module.usecase_items({"usecases": {}})

    described = minimal_manifest()["usecases"][0]
    described["models"][0]["description"] = "Described model."
    described["models"][0]["fields"] = [{"name": "value", "type": "str", "required": False}]
    described["tags"] = ["example"]
    contract = render_contract_module(described)
    assert '"""Described model."""' in contract
    assert "value: str | None = None" in contract
    assert "tags=('example',)" in contract

    assert manifest_module.trim_to_root("app/contracts/example/run/v1.py", "") == (
        "app/contracts/example/run/v1.py"
    )
    assert manifest_module.trim_to_root("/tmp/project/app/contracts/example/run/v1.py", "app") == (
        "app/contracts/example/run/v1.py"
    )
    assert manifest_module.qualname(object()).startswith("<object object")
    assert manifest_module.default_ref_symbol("example.run") == "RUN"
    with pytest.raises(ManifestError, match="must be a non-empty string"):
        manifest_module.required_string({"x": ""}, "x")
    with pytest.raises(ManifestError, match="must be a mapping"):
        manifest_module.required_mapping(None, "value")

    class Args:
        pass

    assert manifest_module.source_file(1) is None
    monkeypatch.setattr("usecaseapi.manifest.inspect.getsourcefile", lambda value: None)
    assert manifest_module.source_file(Args) is None
    monkeypatch.setattr(
        "usecaseapi.manifest.inspect.getsourcefile",
        lambda value: str(tmp_path / "outside.py"),
    )
    assert manifest_module.source_file(Args) == (tmp_path / "outside.py").as_posix()

    missing_module_ref = type(
        "Ref",
        (),
        {"protocol": type("ProtocolType", (), {"__module__": "missing.module"})},
    )()
    assert manifest_module.find_ref_symbol(missing_module_ref) is None
    local_ref = define_usecase(
        type("LocalProtocol", (), {"__module__": __name__}),
        Contract(name="local.run", version=1, input=Input, output=Output),
    )
    assert manifest_module.find_ref_symbol(local_ref) is None

    single_api = UseCaseAPI[None]()
    single_api.bind(EXAMPLE, lambda caller: ExampleImpl())
    monkeypatch.setattr(manifest_module, "source_file", lambda value: "example/usecases/run/v1.py")
    single_manifest = manifest_from_api(single_api)
    assert manifest_module.semantic_from_openapi_manifest(single_manifest)["layout"] == {
        "contracts_root": "example",
        "implementations_root": ".",
        "tests_root": "tests",
        "package": "example",
    }
    monkeypatch.setattr(manifest_module, "source_file", lambda value: None)
    single_without_source_manifest = manifest_from_api(single_api)
    assert manifest_module.semantic_from_openapi_manifest(single_without_source_manifest)[
        "layout"
    ] == {
        "contracts_root": "src/example",
        "implementations_root": "src",
        "tests_root": "tests",
        "package": "example",
    }

    multi_api = UseCaseAPI[None]()
    multi_api.bind(EXAMPLE, lambda caller: ExampleImpl())
    multi_api.bind(RICH, lambda caller: RichImpl())
    multi_manifest = manifest_from_api(multi_api)
    assert manifest_module.semantic_from_openapi_manifest(multi_manifest)["layout"] == {
        "contracts_root": "src",
        "implementations_root": "src",
        "tests_root": "tests",
    }

    assert manifest_module.semantic_manifest(minimal_manifest())["kind"] == (
        manifest_module.LEGACY_MANIFEST_KIND
    )
    assert manifest_module.project_name({}) is None
    assert manifest_module.package_name({}) is None


def test_manifest_v2_openapi_profile_error_branches() -> None:
    """OpenAPI profile validation and normalization failures stay explicit."""
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: ExampleImpl())
    manifest = manifest_from_api(api, project="demo")

    invalid_openapi = deepcopy(manifest)
    invalid_openapi["openapi"] = "3.0.3"
    with pytest.raises(ManifestError, match="manifest.openapi"):
        validate_manifest(invalid_openapi)

    missing_surface = deepcopy(manifest)
    missing_surface.pop("paths")
    missing_surface.pop("components")
    with pytest.raises(ManifestError, match="paths or components"):
        validate_manifest(missing_surface)

    invalid_version = deepcopy(manifest)
    invalid_version["x-usecaseapi"]["version"] = "0.0.0"
    with pytest.raises(ManifestError, match="x-usecaseapi.version"):
        validate_manifest(invalid_version)

    invalid_profile = deepcopy(manifest)
    invalid_profile["x-usecaseapi"]["profile"] = "other"
    with pytest.raises(ManifestError, match="x-usecaseapi.profile"):
        validate_manifest(invalid_profile)

    invalid_manifest_kind = deepcopy(manifest)
    invalid_manifest_kind["x-usecaseapi"]["manifestKind"] = "other"
    with pytest.raises(ManifestError, match="x-usecaseapi.manifestKind"):
        validate_manifest(invalid_manifest_kind)

    skipped_paths = deepcopy(manifest)
    paths = skipped_paths["paths"]
    paths[123] = {"post": {}}
    paths["/_ignored/no_post"] = {"get": {}}
    paths["/_ignored/not_usecase"] = {"post": {"x-usecaseapi": {"kind": "other"}}}
    assert len(manifest_module.semantic_from_openapi_manifest(skipped_paths)["usecases"]) == 1

    path, path_item = next(iter(manifest["paths"].items()))
    operation = path_item["post"]
    with pytest.raises(ManifestError, match="usecase path"):
        manifest_module.openapi_operation_to_usecase(
            "/_usecases/example.run/v2/call",
            operation,
            operation["x-usecaseapi"],
            manifest,
        )


def test_manifest_v2_schema_and_helper_edge_branches() -> None:
    """v2 schema conversion helpers cover unsupported and malformed edge cases."""
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: ExampleImpl())
    manifest = manifest_from_api(api, project="demo")

    assert manifest_module.type_expr_to_schema("Custom", usecase={}) == {}
    assert manifest_module.type_ast_to_schema(
        ast.parse("'fixed'", mode="eval").body,
        usecase={},
    ) == {"const": "fixed"}
    assert (
        manifest_module.type_ast_to_schema(
            ast.parse("lambda: 1", mode="eval").body,
            usecase={},
        )
        == {}
    )
    typing_list = ast.parse("typing.List[str]", mode="eval").body
    assert isinstance(typing_list, ast.Subscript)
    assert manifest_module.subscript_ast_to_schema(typing_list, usecase={}) == {}

    frozenset_type = ast.parse("frozenset[str]", mode="eval").body
    assert isinstance(frozenset_type, ast.Subscript)
    assert manifest_module.subscript_ast_to_schema(frozenset_type, usecase={}) == {}
    assert manifest_module.ast_arg_schema([], 0, usecase={}) == {}

    malformed_model = {
        "properties": {
            1: {"type": "string"},
            "ignored": "not a schema",
            "value": {"type": "integer"},
        },
        "required": ["value"],
    }
    assert manifest_module.schema_to_model("Malformed", malformed_model)["fields"] == [
        {"name": "value", "type": "int", "required": True}
    ]

    missing_class = deepcopy(manifest)
    first_schema = next(iter(missing_class["components"]["schemas"].values()))
    first_schema.pop("title", None)
    first_schema["x-usecaseapi"] = {"kind": "model"}
    with pytest.raises(ManifestError, match="must declare a Python class"):
        manifest_module.semantic_from_openapi_manifest(missing_class)

    with pytest.raises(ManifestError, match="x-usecaseapi.uses must be a mapping"):
        manifest_module.uses_from_extension({"uses": []})
    with pytest.raises(ManifestError, match="x-usecaseapi.uses entries"):
        manifest_module.uses_from_extension({"uses": {"bad": "entry"}})
    with pytest.raises(ManifestError, match="unsupported schema reference"):
        manifest_module.schema_by_ref(manifest, "#/components/responses/Error")

    assert manifest_module.class_name_from_component_ref("#/components/schemas/Plain") == "Plain"

    error_model_manifest = minimal_manifest()
    error_model_usecase = error_model_manifest["usecases"][0]
    error_model_usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example.run",
            "fields": [{"name": "input", "type": "Input", "required": True}],
        }
    ]
    error_model_usecase["raises"] = ["ExampleError"]
    error_model_openapi = manifest_module.openapi_manifest_from_semantic(error_model_manifest)
    payload_schema = error_model_openapi["components"]["schemas"]["ExampleRunV1ExampleErrorPayload"]
    assert payload_schema["properties"]["input"] == {
        "$ref": "#/components/schemas/ExampleRunV1Input"
    }
    assert manifest_module.semantic_from_openapi_manifest(error_model_openapi)["usecases"][0][
        "errors"
    ][0]["fields"] == [{"name": "input", "type": "Input", "required": True}]

    documented = minimal_manifest()
    documented["metadata"] = {"name": "demo"}
    assert "Project: `demo`" in render_manifest_markdown(documented)

    with pytest.raises(ManifestError, match="manifest.usecases"):
        manifest_module.usecase_items_from_semantic({"usecases": {}})

    assert (
        manifest_module.module_from_python_file(
            Path("src/example/contracts/run.py"),
            package="example",
        )
        == "example.contracts.run"
    )
