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

## Manifest tests

Generate and validate the canonical Manifest in CI:

```bash
usecaseapi manifest export composition:usecases --output usecaseapi.ucase.yaml
usecaseapi manifest validate usecaseapi.ucase.yaml
usecaseapi manifest check-sync composition:usecases usecaseapi.ucase.yaml
git diff --exit-code usecaseapi.ucase.yaml
```

## Breaking-change checks

```bash
usecaseapi diff old.ucase.yaml new.ucase.yaml
```

The diff is intentionally conservative. If the same stable version changes input or output models, fields, or declared errors, it reports a breaking change.
