# Testing

UseCaseAPI keeps tests simple because composition is explicit.

## Type conformance

In implementation modules, keep a structural assignment:

```python
_impl: PlaceOrder = PlaceOrderUseCase()
```

Mypy and pyright can then verify the implementation shape.

## Runtime call tests

```python
ctx = AppContext(...)
output = await usecases.caller(ctx).call(PLACE_ORDER, input)
```

## Snapshot tests

Generate and compare snapshots in CI:

```bash
usecaseapi snapshot app.composition:usecases --output usecaseapi.snapshot.json
git diff --exit-code usecaseapi.snapshot.json
```

## Breaking-change checks

```bash
usecaseapi diff old-snapshot.json new-snapshot.json
```

The diff is intentionally conservative. If the same stable version changes input or output schema, it reports a breaking change.
