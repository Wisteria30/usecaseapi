# UseCaseAPI

UseCaseAPI is a Protocol-first Python library for treating same-process usecases as a real, versioned application API.

It is inspired by the developer experience of FastAPI, but it is not a web framework. FastAPI turns Python type hints into a public HTTP API contract. UseCaseAPI turns Python Protocols, Pydantic models, and real Python exception classes into a public contract for your application layer, without forcing HTTP, RPC, serialization, or a dependency-injection container into the hot path.

UseCaseAPI is designed for applications with many internal usecase nodes: workflow-like systems, ROS-like node composition, AI-agent tool surfaces, batch workers, CLIs, FastAPI/Django backends, and systems where AI-assisted coding makes accidental breaking changes easier than before.

## What it gives you

- Code-first usecase contracts using `Protocol`, `Model`, and normal Python exceptions.
- Same-process direct calls with no JSON serialization in the hot path.
- Explicit binding from contract token to implementation factory.
- Declared usecase dependency graph with strict undeclared-call protection.
- Versioned contract identity: `name@vN`.
- Contract snapshots, conservative diffing, Markdown docs, Mermaid graph export, and CLI scaffolding.
- No DI container, no transaction manager, no HTTP/RPC runtime.

## Install

```bash
uv add usecaseapi
```

For local development:

```bash
uv sync --extra dev
uv run pytest
uv run mypy
uv run ruff check .
```

Python support: 3.12, 3.13, and 3.14. Pydantic v2 is required.

## Quick example

Define a contract:

```python
from __future__ import annotations

from typing import ClassVar, Literal, Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseError, UseCaseRef, define_usecase


class Input(Model):
    user_id: str
    sku_id: str
    quantity: int


class Output(Model):
    order_id: str
    status: Literal["accepted"]


class PlaceOrderError(UseCaseError):
    code: ClassVar[str] = "orders.place_order"


class InventoryShortage(PlaceOrderError):
    code: ClassVar[str] = "orders.place_order.inventory_shortage"

    def __init__(self, *, sku_id: str, requested: int, available: int) -> None:
        self.sku_id = sku_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"inventory shortage: sku_id={sku_id}, requested={requested}, available={available}"
        )


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
        known_errors=(InventoryShortage,),
    ),
)
```

Implement it:

```python
from app.contracts.orders.place_order.v1 import Input, Output, PlaceOrder


class PlaceOrderImpl:
    async def __call__(self, input: Input, /) -> Output:
        return Output(order_id="ord_123", status="accepted")


_impl: PlaceOrder = PlaceOrderImpl()
```

Bind and call it:

```python
from dataclasses import dataclass

from usecaseapi import UseCaseAPI


@dataclass(frozen=True)
class AppContext:
    tenant_id: str


usecases = UseCaseAPI[AppContext]()
usecases.bind(PLACE_ORDER, lambda caller: PlaceOrderImpl())

output = await usecases.caller(AppContext(tenant_id="t1")).call(PLACE_ORDER, input)
```

## Scaffold

```bash
usecaseapi scaffold orders.place_order --version 1

# Create the next major contract version by scanning app/contracts/orders/place_order/v*.py
usecaseapi scaffold orders.place_order --next
```

This creates:

```text
app/contracts/orders/place_order/v1.py
app/usecases/orders/place_order.py
tests/test_orders_place_order_v1.py
```

## Why not just write classes yourself?

You can, and for small projects you should. UseCaseAPI becomes useful when you have many internal nodes and you need to know:

- which functions are public application-layer contracts;
- which version each caller depends on;
- which usecase dependencies are allowed;
- which domain exceptions are part of the contract;
- whether AI-assisted changes silently broke a stable contract;
- what the application graph looks like.

UseCaseAPI is a small runtime plus guardrails for that problem.
