# Scaffold

UseCaseAPI includes a scaffold command so versioned contract layout does not depend on memory or tribal rules.

```bash
usecaseapi scaffold commerce place_order --output-root src
```

It creates:

```text
src/commerce/usecases/place_order/v1/place_order_contract.py
src/commerce/usecases/place_order/v1/place_order_usecase.py
tests/commerce/usecases/place_order/v1/test_place_order.py
```

## Create the next major version

For breaking changes, copy the latest existing contract and bump only the contract metadata:

```bash
usecaseapi scaffold commerce place_order --output-root src --next
```

If `v1` is the latest existing version, this copies:

```text
src/commerce/usecases/place_order/v1/place_order_contract.py
```

into:

```text
src/commerce/usecases/place_order/v2/place_order_contract.py
```

and updates `version=1` to `version=2`. This keeps the old version intact while giving
the new version a concrete starting point.

## Options

```bash
usecaseapi scaffold commerce place_order --output-root src --version 2
usecaseapi scaffold commerce place_order --output-root src --next
usecaseapi scaffold commerce place_order --output-root src --dry-run
usecaseapi scaffold commerce place_order --output-root src --force
```

Use `--force` to overwrite generated files. Use `--dry-run` to print what would be created.

The generated test includes a structural Protocol assignment so mypy/pyright can verify that the implementation conforms to the contract:

```python
usecase: PlaceOrder = PlaceOrderUseCase()
```
