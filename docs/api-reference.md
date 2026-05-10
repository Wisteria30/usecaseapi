# API Reference

## `Model`

Base class for contract input and output objects. It extends Pydantic v2 `BaseModel` with `extra="forbid"` and `frozen=True`.

## `UseCaseError`

Base class for domain errors that are part of public usecase contracts. Subclasses should define a stable `code: ClassVar[str]`.

```python
class PlaceOrderError(UseCaseError):
    code: ClassVar[str] = "commerce.place_order"
```

## `UseCase[InputT, OutputT]`

Structural Protocol for async callable usecase implementations.

```python
class PlaceOrder(UseCase[PlaceOrderUseCaseInput, PlaceOrderUseCaseOutput], Protocol):
    async def __call__(self, input: PlaceOrderUseCaseInput, /) -> PlaceOrderUseCaseOutput:
        ...
```

## `Contract`

Runtime metadata for a contract.

Important fields:

- `name`: stable dotted name.
- `version`: major version integer.
- `input`: input model class.
- `output`: output model class.
- `raises`: public exception handling boundary.
- `known_errors`: documented leaf errors.
- `stable`: whether the contract is stable.
- `deprecated`: whether new code should avoid it.
- `superseded_by`: replacement key, if any.

## `define_usecase(protocol, contract)`

Creates a typed `UseCaseRef` token.

## `UseCaseAPI[ContextT]`

Registry and runtime.

```python
api = UseCaseAPI[AppContext]()
api.register(PLACE_ORDER_USECASE)
api.bind(PLACE_ORDER_USECASE, lambda caller: PlaceOrderUseCase())
api.validate()
caller = api.caller(context)
```

## `Caller[ContextT]`

Context-bound call surface.

```python
output = await caller.call(PLACE_ORDER_USECASE, input)
results = await caller.gather(caller.call(A, a), caller.call(B, b))
```

`Caller.gather` uses `asyncio.TaskGroup`, so multiple failures preserve Python `ExceptionGroup` behavior.

## `manifest_from_api(api)`

Creates a YAML-friendly Manifest catalog from a registered `UseCaseAPI` instance.

## `load_manifest(path)` / `dump_manifest(manifest, path)`

Loads and writes validated `.ucase.yaml` Manifest files.

## `validate_manifest(manifest)`

Validates Manifest shape, type expression syntax, error boundaries, model references, and usecase keys.

## `scaffold_from_manifest(manifest)`

Generates Python contract, implementation, and pytest skeletons from Manifest entries.

## `diff_manifests(old, new)`

Performs conservative breaking-change detection.

## `render_manifest_markdown(manifest)` / `render_manifest_graph(manifest)`

Renders human-readable docs and graph diagrams from Manifest data.
