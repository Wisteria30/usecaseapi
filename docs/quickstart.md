# Quickstart

UseCaseAPI starts with a contract module. A contract module is intentionally close to ordinary Python code: Pydantic v2 models, real exception classes, and a structural Protocol.

## 1. Create a contract

```python
# src/commerce/usecases/place_order/v1/place_order_contract.py
from __future__ import annotations

from typing import ClassVar, Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseError, UseCaseRef, define_usecase


class PlaceOrderUseCaseInput(Model):
    user_id: str
    sku_id: str
    quantity: int


class PlaceOrderUseCaseOutput(Model):
    order_id: str


class PlaceOrderError(UseCaseError):
    code: ClassVar[str] = "commerce.place_order"


class PlaceOrder(UseCase[PlaceOrderUseCaseInput, PlaceOrderUseCaseOutput], Protocol):
    async def __call__(self, input: PlaceOrderUseCaseInput, /) -> PlaceOrderUseCaseOutput:
        ...


PLACE_ORDER_USECASE: UseCaseRef[PlaceOrderUseCaseInput, PlaceOrderUseCaseOutput] = define_usecase(
    PlaceOrder,
    Contract(
        name="commerce.place_order",
        version=1,
        input=PlaceOrderUseCaseInput,
        output=PlaceOrderUseCaseOutput,
        raises=(PlaceOrderError,),
    ),
)
```

## 2. Implement it

```python
# src/commerce/usecases/place_order/v1/place_order_usecase.py
from commerce.usecases.place_order.v1.place_order_contract import (
    PlaceOrderUseCaseInput,
    PlaceOrderUseCaseOutput,
)


class PlaceOrderUseCase:
    async def __call__(
        self,
        input: PlaceOrderUseCaseInput,
        /,
    ) -> PlaceOrderUseCaseOutput:
        return PlaceOrderUseCaseOutput(order_id="ord_123")
```

Instantiate the implementation in your composition root or in tests with the
dependencies that project actually uses.

## 3. Compose it

```python
from dataclasses import dataclass

from usecaseapi import UseCaseAPI

from commerce.usecases.place_order.v1.place_order_contract import (
    PLACE_ORDER_USECASE,
    PlaceOrderUseCaseInput,
)
from commerce.usecases.place_order.v1.place_order_usecase import PlaceOrderUseCase


@dataclass(frozen=True)
class AppContext:
    tenant_id: str


usecases = UseCaseAPI[AppContext]()
usecases.bind(PLACE_ORDER_USECASE, lambda caller: PlaceOrderUseCase())
```

## 4. Call it

```python
caller = usecases.caller(AppContext(tenant_id="tenant_a"))
output = await caller.call(
    PLACE_ORDER_USECASE,
    PlaceOrderUseCaseInput(user_id="u1", sku_id="s1", quantity=1),
)
```

The call is same-process and direct. UseCaseAPI does not serialize the input or output.
