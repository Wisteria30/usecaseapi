# Quickstart

UseCaseAPI starts with a contract module. A contract module is intentionally close to ordinary Python code: Pydantic v2 models, real exception classes, and a structural Protocol.

## 1. Create a contract

```python
# app/contracts/orders/place_order/v1.py
from __future__ import annotations

from typing import ClassVar, Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseError, UseCaseRef, define_usecase


class Input(Model):
    user_id: str
    sku_id: str
    quantity: int


class Output(Model):
    order_id: str


class PlaceOrderError(UseCaseError):
    code: ClassVar[str] = "orders.place_order"


class PlaceOrder(UseCase[Input, Output], Protocol):
    async def __call__(self, input: Input, /) -> Output:
        ...


PLACE_ORDER: UseCaseRef[Input, Output] = define_usecase(
    PlaceOrder,
    Contract(
        name="orders.place_order",
        version=1,
        input=Input,
        output=Output,
        raises=(PlaceOrderError,),
    ),
)
```

## 2. Implement it

```python
# app/usecases/orders/place_order.py
from app.contracts.orders.place_order.v1 import Input, Output, PlaceOrder


class PlaceOrderImpl:
    async def __call__(self, input: Input, /) -> Output:
        return Output(order_id="ord_123")


_impl: PlaceOrder = PlaceOrderImpl()
```

`_impl: PlaceOrder = PlaceOrderImpl()` is intentionally boring. It lets mypy and pyright check that the implementation structurally conforms to the public contract.

## 3. Compose it

```python
from dataclasses import dataclass

from usecaseapi import UseCaseAPI

from app.contracts.orders.place_order.v1 import PLACE_ORDER
from app.usecases.orders.place_order import PlaceOrderImpl


@dataclass(frozen=True)
class AppContext:
    tenant_id: str


usecases = UseCaseAPI[AppContext]()
usecases.bind(PLACE_ORDER, lambda caller: PlaceOrderImpl())
```

## 4. Call it

```python
caller = usecases.caller(AppContext(tenant_id="tenant_a"))
output = await caller.call(PLACE_ORDER, Input(user_id="u1", sku_id="s1", quantity=1))
```

The call is same-process and direct. UseCaseAPI does not serialize the input or output.
