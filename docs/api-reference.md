# API Reference

## `Model`

Base class for contract input and output objects. It extends Pydantic v2 `BaseModel` with `extra="forbid"` and `frozen=True`.

## `UseCaseError`

Base class for domain errors that are part of public usecase contracts. Subclasses should define a stable `code: ClassVar[str]`.

```python
class PlaceOrderError(UseCaseError):
    code: ClassVar[str] = "orders.place_order"
```

## `UseCase[InputT, OutputT]`

Structural Protocol for async callable usecase implementations.

```python
class PlaceOrder(UseCase[Input, Output], Protocol):
    async def __call__(self, input: Input, /) -> Output:
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
api.register(PLACE_ORDER)
api.bind(PLACE_ORDER, lambda caller: PlaceOrderImpl())
api.validate()
caller = api.caller(context)
```

## `Caller[ContextT]`

Context-bound call surface.

```python
output = await caller.call(PLACE_ORDER, input)
results = await caller.gather(caller.call(A, a), caller.call(B, b))
```

`Caller.gather` uses `asyncio.TaskGroup`, so multiple failures preserve Python `ExceptionGroup` behavior.

## `snapshot_from_api(api)`

Creates a JSON-serializable snapshot for CI and docs.

## `diff_snapshots(old, new)`

Performs conservative breaking-change detection.

## `render_markdown(api)` / `render_mermaid(api)`

Renders human-readable docs and graph diagrams.
