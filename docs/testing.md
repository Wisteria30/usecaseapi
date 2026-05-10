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

## Manifest tests

Generate and validate the canonical Manifest in CI:

```bash
usecaseapi manifest export app.composition:usecases --output usecaseapi.ucase.yaml
usecaseapi manifest validate usecaseapi.ucase.yaml
usecaseapi manifest check-sync app.composition:usecases usecaseapi.ucase.yaml
git diff --exit-code usecaseapi.ucase.yaml
```

## Breaking-change checks

```bash
usecaseapi diff old.ucase.yaml new.ucase.yaml
```

The diff is intentionally conservative. If the same stable version changes input or output models, fields, or declared errors, it reports a breaking change.
