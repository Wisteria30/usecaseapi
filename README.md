# UseCaseAPI

<p align="center">
  <img src="https://raw.githubusercontent.com/Wisteria30/usecaseapi/main/docs/assets/brand/logo.png" alt="UseCaseAPI" width="720">
</p>

<p align="center">
  <em>Code-first, OpenAPI-inspired contracts for same-process Python use cases.</em>
</p>

<p align="center">
  <a href="https://github.com/Wisteria30/usecaseapi/actions/workflows/ci.yml">
    <img src="https://github.com/Wisteria30/usecaseapi/actions/workflows/ci.yml/badge.svg" alt="CI">
  </a>
  <a href="https://pypi.org/project/usecaseapi/">
    <img src="https://img.shields.io/pypi/v/usecaseapi.svg" alt="PyPI">
  </a>
  <a href="https://pypi.org/project/usecaseapi/">
    <img src="https://img.shields.io/pypi/pyversions/usecaseapi.svg" alt="Python versions">
  </a>
  <a href="https://github.com/Wisteria30/usecaseapi/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT">
  </a>
</p>

---

**Documentation**: <a href="https://github.com/Wisteria30/usecaseapi/tree/main/docs">github.com/Wisteria30/usecaseapi/tree/main/docs</a>

**Source Code**: <a href="https://github.com/Wisteria30/usecaseapi">github.com/Wisteria30/usecaseapi</a>

---

UseCaseAPI gives internal application use cases stable, versioned contracts.

Define a contract with a Python `Protocol`, Pydantic v2 models, and domain exceptions. Bind that contract to an implementation explicitly. Call it in the same process without turning HTTP, RPC, serialization, dependency injection containers, or transaction managers into runtime requirements.

Add it when your application has internal use case nodes that need stable names, versions, input/output schemas, declared dependencies, and a canonical YAML contract catalog. It helps teams and AI coding agents see what can be called, what can fail, and whether a change broke an application-layer contract before that break ships.

It is designed for applications with many internal use case nodes: workflow-like systems, AI-agent tool surfaces, CLIs, batch workers, FastAPI/Django backends, and codebases where accidental application-layer breaking changes are costly.

## Key features

- **Code-first contracts**: use `Protocol`, `Model`, `UseCase`, `UseCaseRef`, and normal Python exceptions.
- **Same-process calls**: call implementations directly, with no JSON serialization in the call path.
- **Explicit bindings**: connect a contract token to an implementation factory in one place.
- **Declared dependencies**: expose and validate which use cases can call which other use cases.
- **Versioned identity**: identify contracts as stable names such as `commerce.place_order@v1`.
- **Manifest artifacts**: generate a YAML catalog, conservative diffs, Markdown docs, and Mermaid graphs.
- **CLI scaffolding**: create a contract, implementation, and test layout from one command.
- **Typed distribution**: ships `py.typed` for downstream type checkers.

## Requirements

UseCaseAPI requires:

- Python `>=3.12,<3.15`
- Pydantic v2
- PyYAML
- Typer

## Installation

```bash
uv add usecaseapi
```

## Example

### Create a contract

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

### Implement it

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

The implementation class is ordinary Python. Instantiate it in your composition root
or in tests with the dependencies that project actually uses.

### Bind and call it

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

caller = usecases.caller(AppContext(tenant_id="tenant_a"))
output = await caller.call(
    PLACE_ORDER_USECASE,
    PlaceOrderUseCaseInput(user_id="u1", sku_id="s1", quantity=1),
)
```

The call is same-process and direct. UseCaseAPI does not serialize the input or output.

## CLI scaffolding

Create the first contract version:

```bash
usecaseapi scaffold commerce place_order --output-root src
```

Create the next major version from the latest existing contract:

```bash
usecaseapi scaffold commerce place_order --output-root src --next
```

The first command creates:

```text
src/commerce/usecases/place_order/v1/place_order_contract.py
src/commerce/usecases/place_order/v1/place_order_usecase.py
tests/commerce/usecases/place_order/v1/test_place_order.py
```

See [docs/scaffold.md](docs/scaffold.md) for the generated layout and options.

## Manifest

Export the canonical contract catalog:

```bash
usecaseapi manifest export composition:usecases --output usecaseapi.ucase.yaml
```

Validate it and check that code still matches it:

```bash
usecaseapi manifest validate usecaseapi.ucase.yaml
usecaseapi manifest check-sync composition:usecases usecaseapi.ucase.yaml
```

Generate Python contract and implementation skeletons from the catalog:

```bash
usecaseapi manifest scaffold usecaseapi.ucase.yaml --root .
```

Render derived outputs:

```bash
usecaseapi docs usecaseapi.ucase.yaml --output usecaseapi.md
usecaseapi graph usecaseapi.ucase.yaml --output usecaseapi.mmd
usecaseapi diff old.ucase.yaml new.ucase.yaml
```

See [docs/scaffold.md](docs/scaffold.md), [docs/manifest.md](docs/manifest.md), and
[docs/llm-manifest-prompt.md](docs/llm-manifest-prompt.md) for generated layouts,
Manifest syntax, and an LLM prompt for converging requirements into `usecaseapi.ucase.yaml`.

## Manifest docs and graph

UseCaseAPI can turn a composed application into inspectable artifacts:

- a canonical YAML Manifest;
- a conservative diff between Manifests;
- Markdown documentation for use cases and dependencies;
- Mermaid graph output for the dependency graph.

See [docs/api-reference.md](docs/api-reference.md), [docs/versioning.md](docs/versioning.md), and [docs/integrations.md](docs/integrations.md).

## What UseCaseAPI is not

UseCaseAPI is not a web framework and does not add HTTP, RPC, serialization, service locators, dependency injection containers, or transaction managers to your application runtime.

You can write plain classes and functions for small projects. UseCaseAPI becomes useful when an application has enough internal use case nodes that stable names, versions, declared dependencies, documented errors, Manifest catalogs, and generated docs start paying for themselves.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run mypy
uv run ruff check .
uv run ruff format --check .
```

For release validation:

```bash
uv build
uv run twine check dist/*
uv run --isolated --no-project --with dist/*.whl scripts/verify_distribution.py
uv run --isolated --no-project --with dist/*.tar.gz scripts/verify_distribution.py
```

See [docs/pypi-publishing.md](docs/pypi-publishing.md) for the publishing workflow.
