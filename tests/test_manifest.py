"""Manifest catalog behavior tests."""

from __future__ import annotations

import ast
import inspect
import json
import runpy

from collections.abc import Callable
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar, Literal, Protocol, cast, get_type_hints
from uuid import UUID

import pytest
import yaml

from pydantic import (
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)

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

ManifestCiFailureCase = Callable[
    [Path], tuple[list[str], tuple[str, ...], tuple[tuple[Path, str], ...]]
]


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


def test_manifest_from_api_rejects_unrepresentable_pydantic_field_constraints() -> None:
    """Code-first export rejects Pydantic constraints the Manifest cannot preserve."""

    class ConstrainedInput(Model):
        value: str = Field(min_length=10)

    class ConstrainedExample(UseCase[ConstrainedInput, Output], Protocol):
        async def __call__(self, input: ConstrainedInput, /) -> Output: ...

    ref = define_usecase(
        ConstrainedExample,
        Contract(name="constrained.run", version=1, input=ConstrainedInput, output=Output),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="constraints"):
        manifest_from_api(api)


def test_manifest_from_api_rejects_pydantic_alias_contract_loss() -> None:
    """Code-first export rejects aliases that would change the published field name."""

    class AliasedInput(Model):
        user_id: str = Field(alias="userId")

    class AliasedExample(UseCase[AliasedInput, Output], Protocol):
        async def __call__(self, input: AliasedInput, /) -> Output: ...

    ref = define_usecase(
        AliasedExample,
        Contract(name="aliased.run", version=1, input=AliasedInput, output=Output),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="alias"):
        manifest_from_api(api)


def test_manifest_from_api_rejects_unrepresented_field_default() -> None:
    """Code-first export rejects non-None defaults that Manifest fields cannot represent."""

    class DefaultedInput(Model):
        region: str = "jp"

    class DefaultedExample(UseCase[DefaultedInput, Output], Protocol):
        async def __call__(self, input: DefaultedInput, /) -> Output: ...

    ref = define_usecase(
        DefaultedExample,
        Contract(name="defaulted.run", version=1, input=DefaultedInput, output=Output),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="default"):
        manifest_from_api(api)


def test_manifest_from_api_rejects_pydantic_field_validator_contract_loss() -> None:
    """Code-first export rejects field validators the Manifest cannot preserve."""

    class ValidatedInput(Model):
        value: str

        @field_validator("value")
        @classmethod
        def reject_empty(cls, value: str) -> str:
            if not value:
                raise ValueError("empty")
            return value

    class ValidatedExample(UseCase[ValidatedInput, Output], Protocol):
        async def __call__(self, input: ValidatedInput, /) -> Output: ...

    ref = define_usecase(
        ValidatedExample,
        Contract(name="validated.run", version=1, input=ValidatedInput, output=Output),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="field_validators"):
        manifest_from_api(api)


def test_manifest_from_api_rejects_pydantic_model_validator_contract_loss() -> None:
    """Code-first export rejects model validators the Manifest cannot preserve."""

    class RangeInput(Model):
        start: int
        end: int

        @model_validator(mode="after")
        def validate_range(self) -> RangeInput:
            if self.end < self.start:
                raise ValueError("invalid range")
            return self

    class RangeExample(UseCase[RangeInput, Output], Protocol):
        async def __call__(self, input: RangeInput, /) -> Output: ...

    ref = define_usecase(
        RangeExample,
        Contract(name="range.run", version=1, input=RangeInput, output=Output),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="model_validators"):
        manifest_from_api(api)


def test_manifest_from_api_rejects_pydantic_field_serializer_contract_loss() -> None:
    """Code-first export rejects field serializers that can change output schema shape."""

    class SerializedOutput(Model):
        value: int

        @field_serializer("value")
        def serialize_value(self, value: int) -> str:
            return str(value)

    class SerializedExample(UseCase[Input, SerializedOutput], Protocol):
        async def __call__(self, input: Input, /) -> SerializedOutput: ...

    ref = define_usecase(
        SerializedExample,
        Contract(name="serialized.run", version=1, input=Input, output=SerializedOutput),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="field_serializers"):
        manifest_from_api(api)


def test_manifest_from_api_rejects_pydantic_computed_field_contract_loss() -> None:
    """Code-first export rejects computed fields that Manifest output models omit."""

    class ComputedOutput(Model):
        value: int

        @computed_field  # type: ignore[prop-decorator]
        @property
        def doubled(self) -> int:
            return self.value * 2

    class ComputedExample(UseCase[Input, ComputedOutput], Protocol):
        async def __call__(self, input: Input, /) -> ComputedOutput: ...

    ref = define_usecase(
        ComputedExample,
        Contract(name="computed.run", version=1, input=Input, output=ComputedOutput),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="computed_fields"):
        manifest_from_api(api)


def test_manifest_from_api_rejects_pydantic_model_config_extra_allow_contract_loss() -> None:
    """Code-first export rejects model config changes the Manifest cannot preserve."""

    class ExtraInput(Model):
        model_config = ConfigDict(extra="allow")

        value: str

    class ExtraExample(UseCase[ExtraInput, Output], Protocol):
        async def __call__(self, input: ExtraInput, /) -> Output: ...

    ref = define_usecase(
        ExtraExample,
        Contract(name="extra.run", version=1, input=ExtraInput, output=Output),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="model_config"):
        manifest_from_api(api)


def test_manifest_from_api_rejects_pydantic_model_config_string_transform_contract_loss() -> None:
    """Code-first export rejects string transform config that changes runtime contract."""

    class TransformInput(Model):
        model_config = ConfigDict(str_strip_whitespace=True)

        value: str

    class TransformExample(UseCase[TransformInput, Output], Protocol):
        async def __call__(self, input: TransformInput, /) -> Output: ...

    ref = define_usecase(
        TransformExample,
        Contract(name="transform.run", version=1, input=TransformInput, output=Output),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="model_config"):
        manifest_from_api(api)


def test_manifest_from_api_rejects_pydantic_model_config_json_schema_extra_contract_loss() -> None:
    """Code-first export rejects schema extras configured at model level."""

    class SchemaExtraInput(Model):
        model_config = ConfigDict(json_schema_extra={"minProperties": 2})

        value: str

    class SchemaExtraExample(UseCase[SchemaExtraInput, Output], Protocol):
        async def __call__(self, input: SchemaExtraInput, /) -> Output: ...

    ref = define_usecase(
        SchemaExtraExample,
        Contract(name="schema-extra.run", version=1, input=SchemaExtraInput, output=Output),
    )
    api = UseCaseAPI[None]().register(ref)

    with pytest.raises(ManifestError, match="model_config"):
        manifest_from_api(api)


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
        (lambda manifest: manifest["usecases"][0].update({"name": "class.run"}), "name"),
        (
            lambda manifest: manifest["usecases"][0]["source"].update(
                {"contract_module": "app.class.run"}
            ),
            "contract_module",
        ),
        (
            lambda manifest: manifest["usecases"][0]["source"].update({"protocol_class": "class"}),
            "protocol_class",
        ),
        (
            lambda manifest: manifest["usecases"][0]["source"].update({"ref": "class"}),
            "ref",
        ),
        (
            lambda manifest: manifest["usecases"][0]["source"].update(
                {"implementation_class": "class"}
            ),
            "implementation_class",
        ),
        (lambda manifest: manifest["usecases"][0].update({"input": "class"}), "input/output"),
        (
            lambda manifest: manifest["usecases"][0]["models"][0].update({"name": "class"}),
            "model name",
        ),
        (
            lambda manifest: manifest["usecases"][0]["models"][0].update(
                {"fields": [{"name": "class", "type": "str"}]}
            ),
            "field name",
        ),
        (
            lambda manifest: manifest["usecases"][0].update(
                {
                    "errors": [{"name": "class", "base": "UseCaseError", "code": "example"}],
                    "raises": ["class"],
                }
            ),
            "error name",
        ),
    ],
)
def test_manifest_validation_rejects_python_keywords_as_identifiers(
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    """Manifest validation rejects Python keywords used as generated identifiers."""
    manifest = minimal_manifest()
    mutate(manifest)

    with pytest.raises(ManifestError, match=message):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "schema",
    [
        {"oneOf": [{"type": "string"}, {"type": "integer"}]},
        {"const": "x"},
        {"type": "array"},
        {"type": "array", "items": False},
        {"type": "object"},
        {"type": "object", "additionalProperties": False},
        {"type": "unknown"},
        {"enum": []},
        {"enum": [{"not": "literal"}]},
        {"anyOf": []},
        {"anyOf": [{"type": "string"}, False]},
    ],
)
def test_openapi_schema_ingest_rejects_unsupported_schema(schema: dict[str, Any]) -> None:
    """OpenAPI schema ingest rejects profile-unsupported schema instead of widening to Any."""
    with pytest.raises(ManifestError):
        manifest_module.schema_to_type_expr(schema)


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
        "contracts_root": "src/app/contracts",
        "implementations_root": "src/app/usecases",
        "tests_root": "specs",
        "package": "app",
    }
    v2_openapi_manifest = manifest_module.openapi_manifest_from_semantic(v2_manifest)
    v2_result = scaffold_from_manifest(
        v2_openapi_manifest,
        root=tmp_path / "v2",
        dry_run=True,
    )
    assert tmp_path / "v2/src/app/contracts/example/run/v1.py" in v2_result.files
    assert tmp_path / "v2/src/app/usecases/example/run.py" in v2_result.files
    assert tmp_path / "v2/specs/example/run/v1/test_run.py" in v2_result.files


def test_manifest_scaffold_rejects_contract_file_outside_root(tmp_path: Path) -> None:
    """Manifest scaffold rejects source contract paths outside the target root."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["source"]["contract_file"] = "../outside.py"

    with pytest.raises(ManifestError, match="contract_file"):
        scaffold_from_manifest(manifest, root=tmp_path)

    assert not (tmp_path.parent / "outside.py").exists()


def test_manifest_scaffold_rejects_implementation_file_outside_root(tmp_path: Path) -> None:
    """Manifest scaffold rejects source implementation paths outside the target root."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["source"]["implementation_file"] = "../outside.py"

    with pytest.raises(ManifestError, match="implementation_file"):
        scaffold_from_manifest(manifest, root=tmp_path)

    assert not (tmp_path.parent / "outside.py").exists()


def test_manifest_scaffold_rejects_generated_test_file_outside_root(tmp_path: Path) -> None:
    """Manifest scaffold applies the same root check to layout-derived test paths."""
    manifest = minimal_manifest()
    manifest["layout"] = {"tests_root": "../outside"}

    with pytest.raises(ManifestError, match="tests_root"):
        scaffold_from_manifest(manifest, root=tmp_path)

    assert not (tmp_path.parent / "outside").exists()


def test_manifest_scaffold_rejects_invalid_python_file_module_segment(
    tmp_path: Path,
) -> None:
    """Manifest scaffold rejects file paths that cannot become Python import modules."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["source"]["implementation_file"] = "app/usecases/bad-name.py"

    with pytest.raises(ManifestError, match="invalid Python module segment"):
        scaffold_from_manifest(manifest, root=tmp_path)


def test_manifest_scaffold_rejects_contract_file_module_mismatch(tmp_path: Path) -> None:
    """Explicit contract_file must match the declared contract_module import target."""
    manifest = minimal_manifest()
    source = manifest["usecases"][0]["source"]
    source["contract_file"] = "app/contracts/other.py"

    with pytest.raises(ManifestError, match="contract_file"):
        scaffold_from_manifest(manifest, root=tmp_path)


def test_manifest_scaffold_rejects_default_contract_file_module_mismatch(
    tmp_path: Path,
) -> None:
    """Default contract paths must also match the declared contract_module import target."""
    manifest = minimal_manifest()
    manifest["layout"] = {
        "contracts_root": "src/contracts",
        "implementations_root": "src/usecases",
        "package": "app",
    }

    with pytest.raises(ManifestError, match="contract_file"):
        scaffold_from_manifest(manifest, root=tmp_path)


def test_manifest_scaffold_rejects_optional_non_nullable_model_field(tmp_path: Path) -> None:
    """Scaffold must not widen optional non-null model fields to nullable Python fields."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "value", "type": "str", "required": False}
    ]

    with pytest.raises(ManifestError, match="optional but non-nullable"):
        scaffold_from_manifest(manifest, root=tmp_path)


def test_manifest_scaffold_rejects_optional_non_nullable_error_field(tmp_path: Path) -> None:
    """Scaffold must not widen optional non-null error payload fields to nullable values."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example.error",
            "fields": [{"name": "reason", "type": "str", "required": False}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    with pytest.raises(ManifestError, match="optional but non-nullable"):
        scaffold_from_manifest(manifest, root=tmp_path)


def test_manifest_scaffold_preserves_nullable_optional_error_field(tmp_path: Path) -> None:
    """Nullable optional error payload fields render with an explicit None default."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example.error",
            "fields": [{"name": "reason", "type": "str | None", "required": False}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    result = scaffold_from_manifest(manifest, root=tmp_path)
    contract_file = next(path for path in result.files if path.name == "v1.py")
    contract = contract_file.read_text()

    assert "def __init__(self, *, reason: str | None = None) -> None:" in contract


def test_manifest_scaffold_rejects_optional_container_with_nullable_items(
    tmp_path: Path,
) -> None:
    """Nullable container items do not make the field itself nullable."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "items", "type": "list[str | None]", "required": False}
    ]

    with pytest.raises(ManifestError, match="optional but non-nullable"):
        scaffold_from_manifest(manifest, root=tmp_path)


def test_manifest_scaffold_rejects_optional_dict_with_nullable_values(tmp_path: Path) -> None:
    """Nullable dict values do not make the field itself nullable."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "lookup", "type": "dict[str, str | None]", "required": False}
    ]

    with pytest.raises(ManifestError, match="optional but non-nullable"):
        scaffold_from_manifest(manifest, root=tmp_path)


def test_manifest_scaffold_rejects_optional_error_container_with_nullable_items(
    tmp_path: Path,
) -> None:
    """Error payload containers with nullable items are still non-null containers."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example.error",
            "fields": [{"name": "details", "type": "list[str | None]", "required": False}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    with pytest.raises(ManifestError, match="optional but non-nullable"):
        scaffold_from_manifest(manifest, root=tmp_path)


def test_manifest_scaffold_escapes_contract_description_python_literals() -> None:
    """Generated contract module descriptions are Python literals, not raw source."""
    manifest = minimal_manifest()
    payload = '"""\nfrom pathlib import Path\nPath("/tmp/usecaseapi_pwned").write_text("x")\n"""'
    manifest["usecases"][0]["description"] = payload

    contract = render_contract_module(manifest["usecases"][0])

    ast.parse(contract)
    assert contract.startswith(repr(payload))


def test_manifest_scaffold_escapes_model_and_error_descriptions(tmp_path: Path) -> None:
    """Generated model and error descriptions cannot break out into Python statements."""
    marker = tmp_path / "injected.txt"
    payload = f'"""\nfrom pathlib import Path\nPath({str(marker)!r}).write_text(\'x\')\n"""'
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["models"][0]["description"] = payload
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example.error",
            "description": payload,
        }
    ]
    usecase["raises"] = ["ExampleError"]

    result = scaffold_from_manifest(manifest, root=tmp_path / "generated")
    contract_file = next(path for path in result.files if path.name == "v1.py")

    ast.parse(contract_file.read_text())
    runpy.run_path(str(contract_file))
    assert not marker.exists()


def test_manifest_scaffold_escapes_error_code_string_literals() -> None:
    """Generated error code assignments and constructor calls are Python literals."""
    payload = 'example"\n    injected = True\n    #'
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": payload,
            "fields": [{"name": "reason", "type": "str"}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    contract = render_contract_module(usecase)

    ast.parse(contract)
    assert f"    code: ClassVar[str] = {payload!r}" in contract
    assert f"        super().__init__({payload!r})" in contract
    assert "injected = True" not in {line.strip() for line in contract.splitlines()}


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


def test_manifest_diff_reports_added_declared_boundaries_for_sync() -> None:
    """Manifest diff reports newly declared dependencies and errors for exact sync checks."""
    old = minimal_manifest()
    old_case = old["usecases"][0]
    old_case["errors"] = [
        {"name": "ExampleError", "base": "UseCaseError", "code": "example"},
        {"name": "ExampleRejected", "base": "ExampleError", "code": "example.rejected"},
    ]
    new = deepcopy(old)
    new_case = new["usecases"][0]
    new_case["uses"] = ["other.run@v1"]
    new_case["raises"] = ["ExampleError"]
    new_case["known_errors"] = ["ExampleRejected"]

    diff = diff_manifests(old, new)

    assert diff.warnings == (
        "added declared errors for example.run@v1: ExampleError",
        "added known errors for example.run@v1: ExampleRejected",
        "added declared uses for example.run@v1: other.run@v1",
    )
    assert manifest_module.contract_check_sync_errors(diff) == (
        "warning: added declared errors for example.run@v1: ExampleError",
        "warning: added known errors for example.run@v1: ExampleRejected",
        "warning: added declared uses for example.run@v1: other.run@v1",
    )


def test_manifest_diff_reports_nested_model_field_changes() -> None:
    """Manifest diff treats nested model field changes as breaking changes."""
    old = minimal_manifest()
    old_case = old["usecases"][0]
    old_case["models"][0]["fields"] = [{"name": "nested", "type": "Nested"}]
    old_case["models"].append(
        {
            "name": "Nested",
            "fields": [{"name": "value", "type": "int"}],
        }
    )
    new = deepcopy(old)
    new_case = new["usecases"][0]
    new_case["models"][2]["fields"] = [{"name": "value", "type": "str"}]

    diff = diff_manifests(old, new)

    assert "changed model fields for example.run@v1" in diff.breaking


def test_manifest_diff_reports_error_payload_nested_model_field_changes() -> None:
    """Manifest diff treats error payload nested model field changes as breaking changes."""
    old = minimal_manifest()
    old_case = old["usecases"][0]
    old_case["models"].append(
        {
            "name": "Detail",
            "fields": [{"name": "value", "type": "int", "required": True}],
        }
    )
    old_case["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "detail", "type": "Detail", "required": True}],
        }
    ]
    old_case["raises"] = ["ExampleError"]
    new = deepcopy(old)
    new_case = new["usecases"][0]
    new_case["models"][2]["fields"] = [{"name": "value", "type": "str", "required": True}]

    diff = diff_manifests(old, new)

    assert "changed model fields for example.run@v1" in diff.breaking


def test_openapi_export_rejects_colliding_dependency_names() -> None:
    """OpenAPI export rejects use dependencies that would overwrite each other."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["uses"] = ["billing.calculate_total@v1", "commerce.calculate_total@v1"]

    with pytest.raises(ManifestError, match="duplicate dependency name"):
        manifest_module.openapi_manifest_from_semantic(manifest)


def test_openapi_export_rejects_colliding_generated_names() -> None:
    """OpenAPI export rejects usecase names that produce duplicate OpenAPI identifiers."""
    manifest = minimal_manifest()
    first = manifest["usecases"][0]
    first["name"] = "pkg.foo_bar"
    first["key"] = "pkg.foo_bar@v1"
    second = deepcopy(first)
    second["name"] = "pkg.foo.bar"
    second["key"] = "pkg.foo.bar@v1"
    manifest["usecases"].append(second)

    with pytest.raises(ManifestError, match="duplicate OpenAPI"):
        manifest_module.openapi_manifest_from_semantic(manifest)


def test_openapi_export_preserves_any_model_field_schema() -> None:
    """OpenAPI export preserves empty schemas for Any model fields."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "payload", "type": "Any", "required": True}
    ]

    exported = manifest_module.openapi_manifest_from_semantic(manifest)

    schema = exported["components"]["schemas"]["ExampleRunV1Input"]
    assert schema["properties"]["payload"] == {}
    assert "payload" in schema["required"]


def test_openapi_export_preserves_any_error_payload_field_schema() -> None:
    """OpenAPI export preserves empty schemas for Any error payload fields."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "payload", "type": "Any", "required": True}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    exported = manifest_module.openapi_manifest_from_semantic(manifest)

    schema = exported["components"]["schemas"]["ExampleRunV1ExampleErrorPayload"]
    assert schema["properties"]["payload"] == {}
    assert "payload" in schema["required"]


def test_openapi_round_trip_preserves_model_refs_containing_v() -> None:
    """OpenAPI ingest preserves component refs for models whose class names contain V."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["models"][0]["fields"] = [
        {"name": "value", "type": "Value", "required": True},
        {"name": "payload", "type": "ApiV2Payload", "required": True},
    ]
    usecase["models"].extend(
        [
            {"name": "Value", "fields": [{"name": "value", "type": "int", "required": True}]},
            {
                "name": "ApiV2Payload",
                "fields": [{"name": "value", "type": "str", "required": True}],
            },
        ]
    )

    exported = manifest_module.openapi_manifest_from_semantic(manifest)
    semantic = manifest_module.semantic_from_openapi_manifest(exported)

    fields = semantic["usecases"][0]["models"][0]["fields"]
    assert fields == [
        {"name": "value", "type": "Value", "required": True},
        {"name": "payload", "type": "ApiV2Payload", "required": True},
    ]


def test_openapi_round_trip_keeps_v1_and_v10_components_separate() -> None:
    """OpenAPI ingest does not treat v10 components as v1 components."""
    manifest = minimal_manifest()
    v10 = deepcopy(manifest["usecases"][0])
    v10["version"] = 10
    v10["key"] = "example.run@v10"
    v10["models"][0]["fields"] = [{"name": "value", "type": "str", "required": True}]
    manifest["usecases"].append(v10)

    exported = manifest_module.openapi_manifest_from_semantic(manifest)
    validate_manifest(exported)
    semantic = manifest_module.semantic_from_openapi_manifest(exported)

    cases = {usecase["key"]: usecase for usecase in semantic["usecases"]}
    assert cases["example.run@v1"]["models"] == [
        {"name": "Input", "fields": []},
        {"name": "Output", "fields": []},
    ]
    assert cases["example.run@v10"]["models"] == [
        {"name": "Input", "fields": [{"name": "value", "type": "str", "required": True}]},
        {"name": "Output", "fields": []},
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda operation: operation["requestBody"]["content"]["application/json"]["schema"].update(
            {"$ref": "#/components/schemas/ExampleRunV1Output"}
        ),
        lambda operation: operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ].update({"$ref": "#/components/schemas/ExampleRunV1Input"}),
    ],
)
def test_openapi_ingest_rejects_operation_schema_mismatch(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """OpenAPI ingest rejects operation schemas that disagree with x-usecaseapi metadata."""
    manifest = manifest_module.openapi_manifest_from_semantic(minimal_manifest())
    operation = manifest["paths"]["/_usecases/example.run/v1/call"]["post"]
    mutate(operation)

    with pytest.raises(ManifestError, match="schema"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest, operation: operation["requestBody"].update({"required": False}),
        lambda manifest, operation: operation.update(
            {
                "parameters": [
                    {
                        "name": "x-tenant-id",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ]
            }
        ),
        lambda manifest, operation: manifest["paths"]["/_usecases/example.run/v1/call"].update(
            {"get": {"operationId": "unexpected"}}
        ),
        lambda manifest, operation: operation["responses"].update(
            {
                "201": {
                    "description": "Created",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ExampleRunV1Output"}
                        }
                    },
                }
            }
        ),
        lambda manifest, operation: operation["requestBody"]["content"].update(
            {
                "text/plain": {
                    "schema": {"type": "string"},
                }
            }
        ),
        lambda manifest, operation: operation["responses"]["200"]["content"].update(
            {
                "text/plain": {
                    "schema": {"type": "string"},
                }
            }
        ),
        lambda manifest, operation: operation.update({"operationId": "unexpected"}),
    ],
)
def test_openapi_ingest_rejects_operation_shape_mismatch(
    mutate: Callable[[dict[str, Any], dict[str, Any]], None],
) -> None:
    """OpenAPI ingest rejects operation and path fields outside the UseCaseAPI profile."""
    manifest = manifest_module.openapi_manifest_from_semantic(minimal_manifest())
    operation = manifest["paths"]["/_usecases/example.run/v1/call"]["post"]
    mutate(manifest, operation)

    with pytest.raises(ManifestError, match="operation|path item"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda extension: extension.update({"action": "stream"}),
        lambda extension: extension.update({"protocol": "other.v1"}),
        lambda extension: extension["context"].update({"required": True}),
        lambda extension: extension["context"].update(
            {"schema": {"$ref": "#/components/schemas/ExampleRunV1Input"}}
        ),
        lambda extension: extension["semantics"].update({"idempotent": True}),
        lambda extension: extension["lifecycle"].update({"deprecated": True}),
        lambda extension: extension.update({"unexpected": True}),
    ],
)
def test_openapi_ingest_rejects_x_usecaseapi_extension_mismatch(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """OpenAPI ingest rejects x-usecaseapi extension metadata outside the runtime profile."""
    manifest = manifest_module.openapi_manifest_from_semantic(minimal_manifest())
    extension = manifest["paths"]["/_usecases/example.run/v1/call"]["post"]["x-usecaseapi"]
    mutate(extension)

    with pytest.raises(ManifestError, match="x-usecaseapi"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda uses: uses["other"].update({"required": False}),
        lambda uses: uses["other"].update({"extra": True}),
        lambda uses: uses.update({"wrong": uses.pop("other")}),
    ],
)
def test_openapi_ingest_rejects_x_usecaseapi_uses_mismatch(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """OpenAPI ingest rejects dependency extension metadata that changes dependency semantics."""
    semantic = minimal_manifest()
    semantic["usecases"][0]["uses"] = ["example.other@v1"]
    manifest = manifest_module.openapi_manifest_from_semantic(semantic)
    uses = manifest["paths"]["/_usecases/example.run/v1/call"]["post"]["x-usecaseapi"]["uses"]
    mutate(uses)

    with pytest.raises(ManifestError, match="x-usecaseapi.uses"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda manifest, operation: operation["responses"]["default"].update(
            {"$ref": "#/components/responses/OtherDomainError"}
        ),
        lambda manifest, operation: manifest["components"]["responses"]["ExampleRunV1DomainError"][
            "content"
        ]["application/json"]["schema"].update({"oneOf": []}),
    ],
)
def test_openapi_ingest_rejects_error_response_schema_mismatch(
    mutate: Callable[[dict[str, Any], dict[str, Any]], None],
) -> None:
    """OpenAPI ingest rejects error response schemas that disagree with error metadata."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [],
        }
    ]
    usecase["raises"] = ["ExampleError"]
    exported = manifest_module.openapi_manifest_from_semantic(manifest)
    operation = exported["paths"]["/_usecases/example.run/v1/call"]["post"]
    mutate(exported, operation)

    with pytest.raises(ManifestError, match="response"):
        validate_manifest(exported)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda schema: schema["properties"]["payload"].update(
            {"$ref": "#/components/schemas/ExampleRunV1Output"}
        ),
        lambda schema: schema["properties"]["error"].update({"enum": ["OtherError"]}),
        lambda schema: schema["properties"]["code"].update({"enum": ["other"]}),
        lambda schema: schema.update({"additionalProperties": True}),
        lambda schema: schema.update({"required": ["code", "error", "message"]}),
        lambda schema: schema["properties"]["message"].update({"type": "integer"}),
        lambda schema: schema["properties"].update({"trace_id": {"type": "string"}}),
    ],
)
def test_openapi_ingest_rejects_error_envelope_schema_mismatch(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """OpenAPI ingest rejects error envelope schemas that disagree with error metadata."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [],
        }
    ]
    usecase["raises"] = ["ExampleError"]
    exported = manifest_module.openapi_manifest_from_semantic(manifest)
    envelope = exported["components"]["schemas"]["ExampleRunV1ExampleErrorEnvelope"]
    mutate(envelope)

    with pytest.raises(ManifestError, match="envelope"):
        validate_manifest(exported)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda schema: schema.update({"type": "array"}),
        lambda schema: schema.update({"additionalProperties": True}),
        lambda schema: schema.update({"properties": []}),
        lambda schema: schema.update({"required": ["missing"]}),
        lambda schema: schema.update({"minProperties": 2}),
        lambda schema: schema.update({"oneOf": [{"type": "object"}]}),
        lambda schema: schema["properties"].update({"extra": "not-a-schema"}),
    ],
)
def test_openapi_ingest_rejects_model_object_schema_mismatch(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """OpenAPI ingest rejects model schemas whose top-level object contract is invalid."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "value", "type": "int", "required": True}
    ]
    exported = manifest_module.openapi_manifest_from_semantic(manifest)
    schema = exported["components"]["schemas"]["ExampleRunV1Input"]
    mutate(schema)

    with pytest.raises(ManifestError, match="object schema"):
        validate_manifest(exported)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda schema: schema.update({"type": "array"}),
        lambda schema: schema.update({"additionalProperties": True}),
        lambda schema: schema.update({"properties": []}),
        lambda schema: schema.update({"required": ["missing"]}),
        lambda schema: schema.update({"minProperties": 2}),
        lambda schema: schema.update({"oneOf": [{"type": "object"}]}),
        lambda schema: schema["properties"].update({"extra": "not-a-schema"}),
    ],
)
def test_openapi_ingest_rejects_error_payload_object_schema_mismatch(
    mutate: Callable[[dict[str, Any]], None],
) -> None:
    """OpenAPI ingest rejects error payload schemas whose object contract is invalid."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "value", "type": "int", "required": True}],
        }
    ]
    usecase["raises"] = ["ExampleError"]
    exported = manifest_module.openapi_manifest_from_semantic(manifest)
    schema = exported["components"]["schemas"]["ExampleRunV1ExampleErrorPayload"]
    mutate(schema)

    with pytest.raises(ManifestError, match="object schema"):
        validate_manifest(exported)


def test_openapi_ingest_rejects_property_schema_unsupported_string_constraint() -> None:
    """OpenAPI ingest rejects model field constraints that cannot round-trip to Manifest types."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "value", "type": "str", "required": True}
    ]
    exported = manifest_module.openapi_manifest_from_semantic(manifest)
    field_schema = exported["components"]["schemas"]["ExampleRunV1Input"]["properties"]["value"]
    field_schema["minLength"] = 10

    with pytest.raises(ManifestError, match="string schema"):
        validate_manifest(exported)


def test_openapi_ingest_rejects_error_payload_property_schema_unsupported_string_constraint() -> (
    None
):
    """OpenAPI ingest rejects error payload field constraints that would be lost."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "reason", "type": "str", "required": True}],
        }
    ]
    usecase["raises"] = ["ExampleError"]
    exported = manifest_module.openapi_manifest_from_semantic(manifest)
    field_schema = exported["components"]["schemas"]["ExampleRunV1ExampleErrorPayload"][
        "properties"
    ]["reason"]
    field_schema["pattern"] = "^[A-Z]+$"

    with pytest.raises(ManifestError, match="string schema"):
        validate_manifest(exported)


def test_openapi_ingest_rejects_property_schema_unsupported_array_constraint() -> None:
    """OpenAPI ingest rejects array field constraints outside the generated profile."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "values", "type": "list[str]", "required": True}
    ]
    exported = manifest_module.openapi_manifest_from_semantic(manifest)
    field_schema = exported["components"]["schemas"]["ExampleRunV1Input"]["properties"]["values"]
    field_schema["minItems"] = 1

    with pytest.raises(ManifestError, match="array schema"):
        validate_manifest(exported)


def test_openapi_ingest_rejects_root_security_requirement() -> None:
    """OpenAPI ingest rejects root security requirements that semantic metadata cannot carry."""
    exported = manifest_module.openapi_manifest_from_semantic(minimal_manifest())
    exported["security"] = [{"ApiKeyAuth": []}]
    exported["components"]["securitySchemes"] = {
        "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    }

    with pytest.raises(ManifestError, match="security"):
        validate_manifest(exported)


def test_openapi_ingest_rejects_root_schema_dialect_mismatch() -> None:
    """OpenAPI ingest rejects root dialect drift that semantic metadata cannot carry."""
    exported = manifest_module.openapi_manifest_from_semantic(minimal_manifest())
    exported["jsonSchemaDialect"] = "https://json-schema.org/draft/2019-09/schema"

    with pytest.raises(ManifestError, match="jsonSchemaDialect"):
        validate_manifest(exported)


def test_openapi_ingest_rejects_root_unsupported_components() -> None:
    """OpenAPI ingest rejects root component sections outside the generated profile."""
    exported = manifest_module.openapi_manifest_from_semantic(minimal_manifest())
    exported["components"]["parameters"] = {"TraceId": {"name": "X-Trace-Id", "in": "header"}}

    with pytest.raises(ManifestError, match="components"):
        validate_manifest(exported)


@pytest.mark.parametrize(
    "type_expr",
    [
        "MissingDetail",
        "list[MissingDetail]",
        "MissingDetail | None",
        "dict[str, MissingDetail]",
        "tuple[MissingDetail, int]",
    ],
)
def test_manifest_validation_rejects_unknown_model_type_reference(type_expr: str) -> None:
    """Manifest validation rejects field types that reference undeclared models."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "detail", "type": type_expr, "required": True}
    ]

    with pytest.raises(ManifestError, match="unknown model type"):
        validate_manifest(manifest)


def test_manifest_validation_rejects_unknown_error_payload_model_type_reference() -> None:
    """Manifest validation rejects error payload types that reference undeclared models."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "detail", "type": "MissingDetail", "required": True}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    with pytest.raises(ManifestError, match="unknown model type"):
        validate_manifest(manifest)


@pytest.mark.parametrize("type_expr", ["list", "dict", "set", "tuple", "Literal"])
def test_manifest_validation_rejects_bare_generic_model_field_type(type_expr: str) -> None:
    """Manifest validation rejects generic field types without type arguments."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "items", "type": type_expr, "required": True}
    ]

    with pytest.raises(ManifestError, match="generic type requires type arguments"):
        validate_manifest(manifest)


@pytest.mark.parametrize("type_expr", ["list", "dict", "set", "tuple", "Literal"])
def test_manifest_validation_rejects_bare_generic_error_payload_type(type_expr: str) -> None:
    """Manifest validation rejects generic error payload types without type arguments."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "items", "type": type_expr, "required": True}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    with pytest.raises(ManifestError, match="generic type requires type arguments"):
        validate_manifest(manifest)


@pytest.mark.parametrize("type_expr", ["str[int]", "UUID[str]", "Input[int]"])
def test_manifest_validation_rejects_unsupported_subscript_model_field_type(
    type_expr: str,
) -> None:
    """Manifest validation rejects unsupported subscript field types."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "bad", "type": type_expr, "required": True}
    ]

    with pytest.raises(ManifestError, match="unsupported generic type"):
        validate_manifest(manifest)


@pytest.mark.parametrize("type_expr", ["str[int]", "UUID[str]", "Input[int]"])
def test_manifest_validation_rejects_unsupported_subscript_error_payload_type(
    type_expr: str,
) -> None:
    """Manifest validation rejects unsupported subscript error payload types."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "bad", "type": type_expr, "required": True}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    with pytest.raises(ManifestError, match="unsupported generic type"):
        validate_manifest(manifest)


@pytest.mark.parametrize("type_expr", ["list[str, int]", "dict[str]", "set[str, int]", "tuple"])
def test_manifest_validation_rejects_incomplete_generic_model_field_type(
    type_expr: str,
) -> None:
    """Manifest validation rejects generic field types with invalid arity."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "bad", "type": type_expr, "required": True}
    ]

    with pytest.raises(ManifestError, match="generic type"):
        validate_manifest(manifest)


@pytest.mark.parametrize("type_expr", ["list[str, int]", "dict[str]", "set[str, int]", "tuple"])
def test_manifest_validation_rejects_incomplete_generic_error_payload_type(
    type_expr: str,
) -> None:
    """Manifest validation rejects generic error payload types with invalid arity."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "bad", "type": type_expr, "required": True}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    with pytest.raises(ManifestError, match="generic type"):
        validate_manifest(manifest)


@pytest.mark.parametrize("type_expr", ["Literal[str]", "Literal[Input]"])
def test_manifest_validation_rejects_non_literal_literal_model_field_type(
    type_expr: str,
) -> None:
    """Manifest validation rejects Literal field types with non-literal values."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "bad", "type": type_expr, "required": True}
    ]

    with pytest.raises(ManifestError, match="Literal values"):
        validate_manifest(manifest)


@pytest.mark.parametrize("type_expr", ["Literal[str]", "Literal[Input]"])
def test_manifest_validation_rejects_non_literal_literal_error_payload_type(
    type_expr: str,
) -> None:
    """Manifest validation rejects Literal error payload types with non-literal values."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "bad", "type": type_expr, "required": True}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    with pytest.raises(ManifestError, match="Literal values"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "type_expr",
    ["int, str", "(int, str)", "[int]", "1", "list[1]", "dict[str, 1]", "str | 1"],
)
def test_manifest_validation_rejects_invalid_model_field_type_ast(type_expr: str) -> None:
    """Manifest validation rejects Python expressions outside the type-expression subset."""
    manifest = minimal_manifest()
    manifest["usecases"][0]["models"][0]["fields"] = [
        {"name": "bad", "type": type_expr, "required": True}
    ]

    with pytest.raises(ManifestError):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "type_expr",
    ["int, str", "(int, str)", "[int]", "1", "list[1]", "dict[str, 1]", "str | 1"],
)
def test_manifest_validation_rejects_invalid_error_payload_type_ast(type_expr: str) -> None:
    """Manifest validation rejects invalid error payload type expressions."""
    manifest = minimal_manifest()
    usecase = manifest["usecases"][0]
    usecase["errors"] = [
        {
            "name": "ExampleError",
            "base": "UseCaseError",
            "code": "example",
            "fields": [{"name": "bad", "type": type_expr, "required": True}],
        }
    ]
    usecase["raises"] = ["ExampleError"]

    with pytest.raises(ManifestError):
        validate_manifest(manifest)


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


def test_manifest_ci_normalizes_historical_base_empty_object_schemas(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Historical base OpenAPI manifests remain comparable without weakening head validation."""
    base = deepcopy(load_manifest("examples/basic/usecaseapi.yaml"))
    schemas = cast(dict[str, object], cast(dict[str, object], base["components"])["schemas"])
    error_payload = cast(dict[str, object], schemas["CommercePlaceOrderV1PlaceOrderErrorPayload"])
    del error_payload["properties"]
    with pytest.raises(ManifestError, match="properties must be a mapping"):
        validate_manifest(base)

    base_path = tmp_path / "base.yaml"
    summary = tmp_path / "contract-check.md"
    json_report = tmp_path / "contract-check.json"
    base_path.write_text(yaml.safe_dump(base, sort_keys=False))
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
            "--base-manifest",
            str(base_path),
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
    assert "base manifest validation failed" not in stdout
    assert "Status: Passed" in markdown
    assert report["status"] == "passed"
    assert report["guard"] == {"failed": False, "removed": [], "changed": [], "added": []}


def manifest_ci_changed_base_case(
    tmp_path: Path,
) -> tuple[list[str], tuple[str, ...], tuple[tuple[Path, str], ...]]:
    """Given a changed base Manifest, return CLI arguments and expected output."""
    base_path = tmp_path / "base.yaml"
    base = load_manifest("examples/basic/usecaseapi.yaml")
    head = deepcopy(base)
    paths = cast(dict[str, object], base["paths"])
    operation = cast(dict[str, object], cast(dict[str, object], next(iter(paths.values())))["post"])
    operation["summary"] = "old summary"
    dump_manifest(base, base_path)
    head_path = tmp_path / "usecaseapi.yaml"
    dump_manifest(head, head_path)
    return (
        ["--manifest", str(head_path), "--base-manifest", str(base_path)],
        ("Status: Failed", "Existing contract versions are immutable"),
        (),
    )


def manifest_ci_unsynchronized_case(
    tmp_path: Path,
) -> tuple[list[str], tuple[str, ...], tuple[tuple[Path, str], ...]]:
    """Given a changed committed Manifest, return CLI arguments and expected output."""
    changed = manifest_module.semantic_from_openapi_manifest(
        load_manifest("examples/basic/usecaseapi.yaml")
    )
    changed["usecases"][0]["output"] = "DifferentOutput"
    changed["usecases"][0]["models"].append({"name": "DifferentOutput", "fields": []})
    changed_path = tmp_path / "changed.yaml"
    changed_path.write_text(yaml.safe_dump(changed, sort_keys=False))
    return (
        ["--manifest", str(changed_path)],
        ("Status: Failed", "breaking: changed output model"),
        (),
    )


def manifest_ci_missing_manifest_case(
    tmp_path: Path,
) -> tuple[list[str], tuple[str, ...], tuple[tuple[Path, str], ...]]:
    """Given a missing Manifest path, return CLI arguments and expected output."""
    summary = tmp_path / "contract-check.md"
    missing = tmp_path / "missing.yaml"
    return (
        ["--manifest", str(missing), "--summary", str(summary)],
        ("Status: Failed",),
        ((summary, str(missing)),),
    )


def manifest_ci_invalid_yaml_case(
    tmp_path: Path,
) -> tuple[list[str], tuple[str, ...], tuple[tuple[Path, str], ...]]:
    """Given an invalid YAML Manifest, return CLI arguments and expected output."""
    bad_manifest = tmp_path / "bad.yaml"
    summary = tmp_path / "contract-check.md"
    json_path = tmp_path / "contract-check.json"
    bad_manifest.write_text("openapi: [unterminated\n")
    return (
        ["--manifest", str(bad_manifest), "--summary", str(summary), "--json", str(json_path)],
        ("Status: Failed",),
        ((summary, "Status: Failed"), (json_path, "manifest validation failed")),
    )


def manifest_ci_target_load_failure_case(
    tmp_path: Path,
) -> tuple[list[str], tuple[str, ...], tuple[tuple[Path, str], ...]]:
    """Given an invalid target import, return CLI arguments and expected output."""
    del tmp_path
    return (
        ["--target", "missing_module:usecases", "--manifest", "usecaseapi.yaml"],
        ("Status: Failed", "target load failed:"),
        (),
    )


def manifest_ci_missing_base_case(
    tmp_path: Path,
) -> tuple[list[str], tuple[str, ...], tuple[tuple[Path, str], ...]]:
    """Given a missing base Manifest path, return CLI arguments and expected output."""
    missing_base = tmp_path / "missing-base.yaml"
    return (
        ["--manifest", "usecaseapi.yaml", "--base-manifest", str(missing_base)],
        (f"base manifest not found: {missing_base}",),
        (),
    )


def manifest_ci_invalid_base_case(
    tmp_path: Path,
) -> tuple[list[str], tuple[str, ...], tuple[tuple[Path, str], ...]]:
    """Given an invalid base Manifest, return CLI arguments and expected output."""
    bad_base = tmp_path / "bad-base.yaml"
    bad_base.write_text("openapi: [unterminated\n")
    return (
        ["--manifest", "usecaseapi.yaml", "--base-manifest", str(bad_base)],
        ("base manifest validation failed:",),
        (),
    )


@pytest.mark.parametrize(
    ("make_case",),
    [
        pytest.param(manifest_ci_changed_base_case, id="changed-base"),
        pytest.param(manifest_ci_unsynchronized_case, id="unsynchronized-manifest"),
        pytest.param(manifest_ci_missing_manifest_case, id="missing-manifest"),
        pytest.param(manifest_ci_invalid_yaml_case, id="invalid-yaml"),
        pytest.param(manifest_ci_target_load_failure_case, id="target-load-failure"),
        pytest.param(manifest_ci_missing_base_case, id="missing-base"),
        pytest.param(manifest_ci_invalid_base_case, id="invalid-base"),
    ],
)
def test_manifest_ci_failure_cases_report_expected_details(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    make_case: ManifestCiFailureCase,
) -> None:
    """The manifest ci command reports each failure mode in a readable form."""
    # Given
    extra_args, stdout_fragments, file_expectations = make_case(tmp_path)
    monkeypatch.chdir("examples/basic")
    monkeypatch.syspath_prepend("src")

    # When
    exit_code = main(
        [
            "manifest",
            "ci",
            "--target",
            "composition:usecases",
            *extra_args,
        ]
    )

    # Then
    assert exit_code == 1
    output = capsys.readouterr().out
    for fragment in stdout_fragments:
        assert fragment in output
    for path, fragment in file_expectations:
        assert fragment in path.read_text()


def test_contract_check_markdown_lists_added_versions() -> None:
    """The contract check report renders allowed additions distinctly from failures."""
    base = load_manifest("examples/basic/usecaseapi.yaml")
    semantic = manifest_module.semantic_from_openapi_manifest(base)
    source_usecase = next(
        usecase for usecase in semantic["usecases"] if usecase["key"] == "commerce.place_order@v1"
    )
    new_usecase = deepcopy(source_usecase)
    new_usecase["version"] = 2
    new_usecase["key"] = "commerce.place_order@v2"
    semantic["usecases"].append(new_usecase)
    head = manifest_module.openapi_manifest_from_semantic(semantic)

    report = manifest_module.ContractCheckReport(
        manifest="usecaseapi.yaml",
        target="composition:usecases",
        manifest_valid=True,
        synchronized=True,
        guard=guard_manifests(base, head),
        errors=(),
    )

    markdown = manifest_module.render_contract_check_markdown(report)

    assert "Failures:\n- none" in markdown
    assert "Additions:\n- `commerce.place_order@v2`" in markdown


def test_immutable_usecase_index_ignores_non_operation_path_items() -> None:
    """The immutable index only includes POST usecase operations."""
    manifest = deepcopy(load_manifest("examples/basic/usecaseapi.yaml"))
    paths = cast(dict[str, object], manifest["paths"])
    paths["/_ignored/not-an-object"] = []
    paths["/_ignored/no-post"] = {"get": {"operationId": "ignored"}}
    paths["/_ignored/post-without-extension"] = {
        "post": {"operationId": "ignored_without_extension"}
    }
    paths["/_ignored/post-with-non-usecase-extension"] = {
        "post": {
            "operationId": "ignored_non_usecase",
            "x-usecaseapi": {"kind": "adapter"},
        }
    }

    index = manifest_module.immutable_usecase_index(manifest)

    assert "commerce.check_availability@v1" in index
    assert all(not key.startswith("_ignored") for key in index)


def test_reachable_component_refs_handles_cycles_once() -> None:
    """Reachable component discovery terminates on recursive local references."""
    manifest = {
        "components": {
            "schemas": {
                "A": {"$ref": "#/components/schemas/B"},
                "B": {"$ref": "#/components/schemas/A"},
            }
        }
    }
    operation = {"requestBody": {"$ref": "#/components/schemas/A"}}

    refs = manifest_module._reachable_component_refs(manifest=manifest, operation=operation)

    assert refs == {("schemas", "A"), ("schemas", "B")}


def test_root_error_metadata_and_ref_helpers_handle_empty_or_invalid_values() -> None:
    """Private normalization helpers reject non-component refs without fallback behavior."""
    assert manifest_module._referenced_error_metadata(root_extension={}, refs=set()) == {}
    assert (
        manifest_module._referenced_error_metadata(
            root_extension={"components": {"errors": []}},
            refs=set(),
        )
        == {}
    )
    assert manifest_module._local_component_ref_from_string("#/components/schemas") is None
    assert manifest_module.sort_json_like(("b", {"z": 1, "a": 2})) == ["b", {"a": 2, "z": 1}]


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
    assert contract_text.startswith(repr("Creates an order after inventory has been confirmed."))
    assert repr("Input required to place an order.") in contract_text
    assert repr("Accepted order result.") in contract_text
    assert usecase_text.startswith(repr("Creates an order after inventory has been confirmed."))
    assert (
        "class PlaceOrderUseCase:\n"
        f"    {repr('Creates an order after inventory has been confirmed.')}" in (usecase_text)
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
    import usecaseapi._manifest.code_first as code_first_module
    import usecaseapi._manifest.code_first_types as code_first_types_module

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

    monkeypatch.setattr(code_first_types_module, "get_type_hints", failing_class_hints)
    assert manifest_module.error_fields(AnnotatedError) == [
        {"name": "detail", "type": "str", "required": True}
    ]

    original_signature = inspect.signature

    def failing_signature(value: Any) -> object:
        if value is VariadicError.__init__:
            raise ValueError("no signature")
        return original_signature(value)

    monkeypatch.setattr(
        "usecaseapi._manifest.code_first_types.inspect.signature", failing_signature
    )
    assert manifest_module.error_fields(VariadicError) == []
    monkeypatch.setattr(
        "usecaseapi._manifest.code_first_types.inspect.signature", original_signature
    )
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
    described["models"][0]["fields"] = [{"name": "value", "type": "str | None", "required": False}]
    described["tags"] = ["example"]
    contract = render_contract_module(described)
    assert repr("Described model.") in contract
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
    monkeypatch.setattr("usecaseapi._manifest.common.inspect.getsourcefile", lambda value: None)
    assert manifest_module.source_file(Args) is None
    monkeypatch.setattr(
        "usecaseapi._manifest.common.inspect.getsourcefile",
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
    monkeypatch.setattr(
        code_first_module, "source_file", lambda value: "example/usecases/run/v1.py"
    )
    single_manifest = manifest_from_api(single_api)
    assert manifest_module.semantic_from_openapi_manifest(single_manifest)["layout"] == {
        "contracts_root": "example",
        "implementations_root": ".",
        "tests_root": "tests",
        "package": "example",
    }
    monkeypatch.setattr(code_first_module, "source_file", lambda value: None)
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

    invalid_path_key = deepcopy(manifest)
    invalid_path_key["paths"][123] = {"post": {}}
    with pytest.raises(ManifestError, match="path keys"):
        manifest_module.semantic_from_openapi_manifest(invalid_path_key)

    invalid_path_item = deepcopy(manifest)
    invalid_path_item["paths"]["/_ignored/no_post"] = {"get": {}}
    with pytest.raises(ManifestError, match="path item"):
        manifest_module.semantic_from_openapi_manifest(invalid_path_item)

    invalid_operation_kind = deepcopy(manifest)
    invalid_operation_kind["paths"]["/_ignored/not_usecase"] = {
        "post": {"x-usecaseapi": {"kind": "other"}}
    }
    with pytest.raises(ManifestError, match="usecase operation"):
        manifest_module.semantic_from_openapi_manifest(invalid_operation_kind)

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


def test_manifest_v2_openapi_profile_remaining_error_branches() -> None:
    """OpenAPI profile validation rejects remaining malformed generated-profile shapes."""
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: ExampleImpl())
    manifest = manifest_from_api(api, project="demo")

    def operation_of(candidate: dict[str, Any]) -> dict[str, Any]:
        path_item = next(iter(candidate["paths"].values()))
        return cast(dict[str, Any], path_item["post"])

    def assert_invalid(mutate: Callable[[dict[str, Any]], None], match: str) -> None:
        candidate = deepcopy(manifest)
        mutate(candidate)
        with pytest.raises(ManifestError, match=match):
            validate_manifest(candidate)

    assert_invalid(lambda candidate: candidate.__setitem__("unexpected", True), "unsupported keys")
    assert_invalid(lambda candidate: candidate.__setitem__("kind", "other"), "manifest kind")
    assert_invalid(lambda candidate: candidate.__setitem__("servers", []), "manifest.servers")
    assert_invalid(lambda candidate: candidate.__setitem__("tags", {}), "manifest.tags")
    assert_invalid(lambda candidate: candidate["tags"].append("bad"), "tags\\[1\\]")
    assert_invalid(lambda candidate: candidate["tags"][0].__setitem__("x", True), "tags\\[0\\]")
    assert_invalid(lambda candidate: candidate["tags"][0].__setitem__("name", ""), "tags\\[0\\]")
    assert_invalid(
        lambda candidate: candidate["components"].__setitem__("responses", []),
        "components.responses",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"].__setitem__("unexpected", True),
        "x-usecaseapi has unsupported keys",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"].__setitem__("defaults", {}),
        "x-usecaseapi.defaults",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"].__setitem__("protocols", {}),
        "x-usecaseapi.protocols",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["runtimes"].__setitem__("js", {}),
        "runtimes must contain only python",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["runtimes"]["python"].__setitem__(
            "unexpected", True
        ),
        "runtimes.python has unsupported keys",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["runtimes"]["python"].__setitem__(
            "language", "ruby"
        ),
        "language",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["runtimes"]["python"].__setitem__(
            "version", ">=3.11"
        ),
        "version",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["runtimes"]["python"].__setitem__(
            "roots", {"contracts": "src"}
        ),
        "roots must define",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["runtimes"]["python"]["roots"].__setitem__(
            "contracts", ""
        ),
        "roots.contracts",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["runtimes"]["python"].__setitem__(
            "package", ""
        ),
        "package",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["components"].__setitem__("unexpected", {}),
        "x-usecaseapi.components",
    )

    invalid_extension = deepcopy(operation_of(manifest)["x-usecaseapi"])
    invalid_extension["kind"] = "query"
    with pytest.raises(ManifestError, match="kind"):
        manifest_module.validate_openapi_operation_extension(
            invalid_extension,
            operation=operation_of(manifest),
        )
    assert_invalid(
        lambda candidate: operation_of(candidate)["x-usecaseapi"]["context"].__setitem__(
            "unexpected", True
        ),
        "context has unsupported keys",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["x-usecaseapi"]["context"].__setitem__(
            "source", "request"
        ),
        "context.source",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["x-usecaseapi"]["lifecycle"].__setitem__(
            "unexpected", True
        ),
        "lifecycle has unsupported keys",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["x-usecaseapi"]["lifecycle"].__setitem__(
            "stability", "beta"
        ),
        "lifecycle.stability",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["x-usecaseapi"]["lifecycle"].__setitem__(
            "deprecated", "false"
        ),
        "lifecycle.deprecated",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["x-usecaseapi"]["lifecycle"].__setitem__(
            "supersededBy", 1
        ),
        "supersededBy",
    )
    with pytest.raises(ManifestError, match="uses must be a mapping"):
        manifest_module.validate_openapi_operation_uses({"uses": []})
    with pytest.raises(ManifestError, match="uses entries"):
        manifest_module.validate_openapi_operation_uses({"uses": {1: {"key": "a@v1"}}})
    with pytest.raises(ManifestError, match="path item"):
        manifest_module.validate_openapi_path_item("/bad", [])
    assert_invalid(
        lambda candidate: operation_of(candidate)["requestBody"].__setitem__("description", "x"),
        "requestBody",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["responses"]["200"].__setitem__("headers", {}),
        "responses.200",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["responses"]["default"].__setitem__(
            "description", "x"
        ),
        "responses.default",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["requestBody"]["content"].__setitem__(
            "text/plain", {}
        ),
        "application/json",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["requestBody"]["content"][
            "application/json"
        ].__setitem__("example", {}),
        "application/json must contain only schema",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["x-usecaseapi"]["input"].__setitem__(
            "schema", "#/components/schemas/Wrong"
        ),
        "input.schema",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["x-usecaseapi"]["output"].__setitem__(
            "schema", "#/components/schemas/Wrong"
        ),
        "output.schema",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["requestBody"]["content"]["application/json"][
            "schema"
        ].__setitem__("$ref", "#/components/schemas/Wrong"),
        "requestBody schema",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["responses"]["200"]["content"][
            "application/json"
        ]["schema"].__setitem__("$ref", "#/components/schemas/Wrong"),
        "200 response schema",
    )
    assert_invalid(
        lambda candidate: operation_of(candidate)["responses"]["default"].__setitem__(
            "$ref", "#/components/responses/Wrong"
        ),
        "default response",
    )

    response_ref = operation_of(manifest)["responses"]["default"]["$ref"]
    assert_invalid(
        lambda candidate: candidate["components"]["responses"][
            response_ref.removeprefix("#/components/responses/")
        ]["content"]["application/json"]["schema"].__setitem__("oneOf", {}),
        "oneOf",
    )
    assert_invalid(
        lambda candidate: candidate["components"]["responses"][
            response_ref.removeprefix("#/components/responses/")
        ]["content"]["application/json"]["schema"].__setitem__("oneOf", ["bad"]),
        "oneOf entries",
    )


def test_manifest_v2_error_schema_remaining_error_branches() -> None:
    """Error metadata and envelope validation cover remaining drift branches."""
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: ExampleImpl())
    manifest = manifest_from_api(api, project="demo")
    identity = {"name": "example.run", "version": 1}
    error_key = manifest_module.component_name(identity, "ExampleError")
    payload_ref = manifest_module.component_ref_path(
        manifest_module.component_name(identity, "ExampleErrorPayload")
    )
    envelope_ref = manifest_module.component_ref_path(
        manifest_module.component_name(identity, "ExampleErrorEnvelope")
    )
    envelope_key = envelope_ref.removeprefix("#/components/schemas/")

    with pytest.raises(ManifestError, match="unsupported response reference"):
        manifest_module.openapi_error_response_envelope_refs(manifest, "#/bad/Response")
    assert (
        manifest_module.errors_from_components(
            {
                **manifest,
                "x-usecaseapi": {
                    **manifest["x-usecaseapi"],
                    "components": {"errors": {1: "bad"}},
                },
            },
            name="example.run",
            version=1,
        )
        == []
    )

    def assert_invalid(mutate: Callable[[dict[str, Any]], None], match: str) -> None:
        candidate = deepcopy(manifest)
        mutate(candidate)
        with pytest.raises(ManifestError, match=match):
            validate_manifest(candidate)

    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["components"]["errors"][error_key].__setitem__(
            "payloadSchema", "#/components/schemas/Wrong"
        ),
        "payloadSchema",
    )
    assert_invalid(
        lambda candidate: candidate["x-usecaseapi"]["components"]["errors"][error_key].__setitem__(
            "envelopeSchema", "#/components/schemas/Wrong"
        ),
        "envelopeSchema",
    )
    assert_invalid(
        lambda candidate: candidate["components"]["schemas"][envelope_key].__setitem__(
            "additionalProperties", True
        ),
        "forbid extra fields",
    )
    assert_invalid(
        lambda candidate: candidate["components"]["schemas"][envelope_key].__setitem__(
            "required", ["code"]
        ),
        "required fields",
    )
    assert_invalid(
        lambda candidate: candidate["components"]["schemas"][envelope_key].__setitem__(
            "properties", {"code": {"type": "string"}}
        ),
        "properties",
    )
    assert_invalid(
        lambda candidate: candidate["components"]["schemas"][envelope_key]["properties"][
            "payload"
        ].__setitem__("$ref", "#/components/schemas/Wrong"),
        "payload must",
    )
    assert_invalid(
        lambda candidate: candidate["components"]["schemas"][envelope_key]["properties"][
            "message"
        ].__setitem__("type", "integer"),
        "message",
    )
    assert_invalid(
        lambda candidate: candidate["components"]["schemas"][envelope_key]["properties"][
            "code"
        ].__setitem__("type", "integer"),
        "code must be string",
    )
    assert (
        manifest_module.openapi_error_envelope_refs(
            {
                **manifest,
                "x-usecaseapi": {
                    **manifest["x-usecaseapi"],
                    "components": {},
                },
            },
            identity,
            [],
        )
        == []
    )
    with pytest.raises(ManifestError, match="payloadSchema"):
        manifest_module.openapi_error_envelope_refs(
            {
                **manifest,
                "x-usecaseapi": {
                    **manifest["x-usecaseapi"],
                    "components": {
                        "errors": {
                            error_key: {
                                **manifest["x-usecaseapi"]["components"]["errors"][error_key],
                                "payloadSchema": payload_ref + "Wrong",
                            }
                        }
                    },
                },
            },
            identity,
            ["ExampleError"],
        )


def test_manifest_openapi_generation_duplicate_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAPI conversion rejects duplicate generated paths, operations, schemas, and responses."""
    import usecaseapi._manifest.openapi as openapi_module

    base = minimal_manifest()["usecases"][0]

    duplicate_path = deepcopy(minimal_manifest())
    duplicate_path["usecases"].append(deepcopy(base))
    with monkeypatch.context() as scoped:
        scoped.setattr(openapi_module, "openapi_components", lambda usecases: {"schemas": {}})
        with pytest.raises(ManifestError, match="duplicate OpenAPI path"):
            manifest_module.openapi_manifest_from_semantic(duplicate_path)

        duplicate_operation = deepcopy(minimal_manifest())
        second = deepcopy(base)
        second["name"] = "example_run"
        duplicate_operation["usecases"].append(second)
        with pytest.raises(ManifestError, match="duplicate OpenAPI operationId"):
            manifest_module.openapi_manifest_from_semantic(duplicate_operation)

    duplicate_model = deepcopy(base)
    duplicate_model["models"].append({"name": "Input", "fields": []})
    with pytest.raises(ManifestError, match="duplicate OpenAPI schema component"):
        manifest_module.openapi_components([duplicate_model])

    duplicate_payload = deepcopy(base)
    duplicate_payload["models"].append({"name": "ExampleErrorPayload", "fields": []})
    duplicate_payload["errors"] = [
        {"name": "ExampleError", "base": "UseCaseError", "code": "example.run", "fields": []}
    ]
    with pytest.raises(ManifestError, match="duplicate OpenAPI schema component"):
        manifest_module.openapi_components([duplicate_payload])

    duplicate_envelope = deepcopy(base)
    duplicate_envelope["models"].append({"name": "ExampleErrorEnvelope", "fields": []})
    duplicate_envelope["errors"] = [
        {"name": "ExampleError", "base": "UseCaseError", "code": "example.run", "fields": []}
    ]
    with pytest.raises(ManifestError, match="duplicate OpenAPI schema component"):
        manifest_module.openapi_components([duplicate_envelope])

    response_one = {
        "name": "a.b",
        "version": 1,
        "input": "Input",
        "output": "Output",
        "models": [{"name": "Input", "fields": []}, {"name": "Output", "fields": []}],
        "errors": [{"name": "FirstError", "base": "UseCaseError", "code": "first", "fields": []}],
        "raises": ["FirstError"],
    }
    response_two = {
        "name": "a_b",
        "version": 1,
        "input": "OtherInput",
        "output": "OtherOutput",
        "models": [{"name": "OtherInput", "fields": []}, {"name": "OtherOutput", "fields": []}],
        "errors": [{"name": "SecondError", "base": "UseCaseError", "code": "second", "fields": []}],
        "raises": ["SecondError"],
    }
    with pytest.raises(ManifestError, match="duplicate OpenAPI response component"):
        manifest_module.openapi_components([response_one, response_two])

    duplicate_error = deepcopy(base)
    duplicate_error["errors"] = [
        {"name": "ExampleError", "base": "UseCaseError", "code": "example.run", "fields": []}
    ]
    with pytest.raises(ManifestError, match="duplicate OpenAPI error component"):
        manifest_module.openapi_error_components([duplicate_error, duplicate_error])


def test_manifest_schema_conversion_remaining_error_branches() -> None:
    """Schema-to-type conversion rejects unsupported JSON Schema edge cases."""
    with pytest.raises(ManifestError, match="unsupported string schema format"):
        manifest_module.schema_to_type_expr({"type": "string", "format": "email"})
    with pytest.raises(ManifestError, match="contentEncoding"):
        manifest_module.schema_to_type_expr({"type": "string", "contentEncoding": "gzip"})
    with pytest.raises(ManifestError, match="cannot combine"):
        manifest_module.schema_to_type_expr(
            {"type": "string", "format": "uuid", "contentEncoding": "base64"}
        )
    assert manifest_module.schema_to_type_expr({"type": "string", "contentEncoding": "base64"}) == (
        "bytes"
    )
    with pytest.raises(ManifestError, match="prefixItems"):
        manifest_module.schema_to_type_expr({"type": "array", "prefixItems": []})
    with pytest.raises(ManifestError, match="minItems/maxItems"):
        manifest_module.schema_to_type_expr(
            {"type": "array", "prefixItems": [{"type": "string"}], "minItems": 0, "maxItems": 1}
        )
    with pytest.raises(ManifestError, match="uniqueItems"):
        manifest_module.schema_to_type_expr(
            {"type": "array", "items": {"type": "string"}, "uniqueItems": False}
        )
    with pytest.raises(ManifestError, match="enum schema must not be empty"):
        manifest_module.schema_to_type_expr({"enum": []})
    with pytest.raises(ManifestError, match="supported Literal"):
        manifest_module.schema_to_type_expr({"enum": [[]]})
    with pytest.raises(ManifestError, match="anyOf"):
        manifest_module.schema_to_type_expr({"anyOf": []})
    with pytest.raises(ManifestError, match="schema.type"):
        manifest_module.schema_to_type_expr({"type": 1})
    with pytest.raises(ManifestError, match="unsupported schema type"):
        manifest_module.schema_to_type_expr({"type": "weird"})
    with pytest.raises(ManifestError, match="prefixItems entries"):
        manifest_module.schema_to_type_expr(
            {"type": "array", "prefixItems": ["bad"], "minItems": 1, "maxItems": 1}
        )
    with pytest.raises(ManifestError, match="items schema"):
        manifest_module.schema_to_type_expr({"type": "array"})
    with pytest.raises(ManifestError, match="additionalProperties"):
        manifest_module.schema_to_type_expr({"type": "object"})
    with pytest.raises(ManifestError, match="unsupported schema reference"):
        manifest_module.class_name_from_component_ref("#/components/responses/Error")
    with pytest.raises(ManifestError, match="component prefix"):
        manifest_module.class_name_from_component_ref(
            "#/components/schemas/OtherName",
            component_name_prefix="Expected",
        )
    with pytest.raises(ManifestError, match="missing a class name"):
        manifest_module.class_name_from_component_ref(
            "#/components/schemas/Expected",
            component_name_prefix="Expected",
        )
    with pytest.raises(ManifestError, match="invalid class name"):
        manifest_module.class_name_from_component_ref(
            "#/components/schemas/Expectedbad-name",
            component_name_prefix="Expected",
        )
    api = UseCaseAPI[None]()
    api.bind(EXAMPLE, lambda caller: ExampleImpl())
    model_manifest = manifest_from_api(api)
    assert (
        manifest_module.models_from_components(
            {
                **model_manifest,
                "components": {"schemas": {"Ignored": "bad"}},
            },
            name="example.run",
            version=1,
        )
        == []
    )
    schemas = model_manifest["components"]["schemas"]
    input_schema = schemas.pop("ExampleRunV1Input")
    schemas["WrongInput"] = input_schema
    with pytest.raises(ManifestError, match="schema component"):
        manifest_module.models_from_components(model_manifest, name="example.run", version=1)
    with pytest.raises(ManifestError, match="property names"):
        manifest_module.validate_openapi_object_model_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {1: {"type": "string"}},
                "required": [],
            },
            name="Bad",
        )
    with pytest.raises(ManifestError, match="required must be"):
        manifest_module.validate_openapi_object_model_schema(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {"value": {"type": "string"}},
                "required": [1],
            },
            name="Bad",
        )


def test_manifest_type_reference_and_path_remaining_error_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Type reference, file path, and reachability helpers cover remaining guard branches."""
    with pytest.raises(ManifestError, match="generic type requires type arguments"):
        manifest_module.validate_type_expr_references(
            "list",
            model_names={"Input"},
            context="model Input",
        )
    assert manifest_module.type_expr_allows_none("Literal[None]") is True
    assert manifest_module.type_expr_allows_none("list[None]") is False
    with pytest.raises(ManifestError, match="dict' requires a str key"):
        manifest_module.validate_type_expr("dict[int, str]")
    with pytest.raises(ManifestError, match="tuple' requires at least one argument"):
        manifest_module.validate_type_expr("tuple[()]")
    with pytest.raises(ManifestError, match="Literal values require"):
        manifest_module.validate_type_expr("Literal[()]")
    assert manifest_module.top_level_type_ast_allows_none(ast.parse("1 + 2", mode="eval").body) is (
        False
    )

    class AbsolutePath:
        suffix = ".py"

        def __init__(self, value: str) -> None:
            self.value = value

        def is_absolute(self) -> bool:
            return True

    import usecaseapi._manifest.common as common_module

    monkeypatch.setattr(common_module, "Path", AbsolutePath)
    with pytest.raises(ManifestError, match="must be a relative path"):
        manifest_module.validate_manifest_file_path("absolute.py", context="path")
    monkeypatch.setattr(common_module, "Path", Path)

    with pytest.raises(ManifestError, match="must end with .py"):
        manifest_module.validate_manifest_file_path("generated.txt", context="path")
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ManifestError, match="scaffold root"):
        manifest_module.safe_manifest_file_under_root(root, "linked/generated.py", context="path")
    assert manifest_module.reachable_model_names(
        {"input": "Input", "output": "Missing", "errors": []},
        {"Input": []},
    ) == {"Input"}


def test_manifest_contract_check_base_and_normalization_remaining_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Contract check base loading and normalization cover malformed historical inputs."""
    summary = tmp_path / "summary.md"
    invalid_base = tmp_path / "base.yaml"
    invalid_base.write_text("- not\n- mapping\n")
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
            "--base-manifest",
            str(invalid_base),
            "--summary",
            str(summary),
        ]
    )

    assert exit_code == 1
    assert "manifest must be a YAML mapping" in summary.read_text()
    legacy = {"kind": manifest_module.LEGACY_MANIFEST_KIND}
    assert manifest_module.normalize_contract_check_base_manifest(legacy) is legacy
    assert manifest_module.normalize_contract_check_base_manifest({"openapi": "3.1.0"}) == {
        "openapi": "3.1.0"
    }


def test_manifest_model_validation_remaining_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model and field representability guards cover remaining unsupported metadata."""

    class PlainDecoratorsModel(Model):
        value: str

    monkeypatch.setattr(PlainDecoratorsModel, "__pydantic_decorators__", None)
    manifest_module.validate_representable_model(PlainDecoratorsModel)

    class FactoryModel(Model):
        value: str = Field(default_factory=str)

    class JsonExtraModel(Model):
        value: str = Field(json_schema_extra={"x": True})

    class TitledModel(Model):
        value: str = Field(title="Value")

    class ExampledModel(Model):
        value: str = Field(examples=["x"])

    class DeprecatedModel(Model):
        value: str = Field(deprecated=True)

    field_cases: list[tuple[type[Any], str]] = [
        (FactoryModel, "default_factory"),
        (JsonExtraModel, "JSON Schema extras"),
        (TitledModel, "schema title"),
        (ExampledModel, "schema examples"),
        (DeprecatedModel, "deprecation metadata"),
    ]
    for model_type, match in field_cases:
        with pytest.raises(ManifestError, match=match):
            manifest_module.validate_representable_field("value", model_type.model_fields["value"])
