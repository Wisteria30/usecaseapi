# Testing

UseCaseAPI keeps tests simple because composition is explicit.

## Type conformance

Keep structural Protocol assignments in tests, where dependencies can be built
explicitly:

```python
def test_place_order_usecase_matches_contract() -> None:
    usecase: PlaceOrder = PlaceOrderUseCase(...)
    assert usecase.__class__ is PlaceOrderUseCase
```

Avoid module-level implementation instances in production code. They force import-time
dependency construction and make complex dependency graphs harder to compose.

## Runtime call tests

```python
ctx = AppContext(...)
output = await usecases.caller(ctx).call(PLACE_ORDER_USECASE, input)
```

## Snapshot tests

Generate and compare snapshots in CI:

```bash
usecaseapi snapshot composition:usecases --output usecaseapi.snapshot.json
git diff --exit-code usecaseapi.snapshot.json
```

## Breaking-change checks

```bash
usecaseapi diff old-snapshot.json new-snapshot.json
```

The diff is intentionally conservative. If the same stable version changes input or output schema, it reports a breaking change.
