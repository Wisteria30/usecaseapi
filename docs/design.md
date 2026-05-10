# Design

UseCaseAPI is built around one idea: a usecase should be treated as a versioned application API even when it is only called inside the same process.

## Core principles

1. **Python code is the source of truth.** Contracts are ordinary Python modules. No external IDL is required.
2. **Protocol-first.** The callable shape is represented by `typing.Protocol`, not by decorators or subclassing requirements.
3. **Exceptions are exceptions.** Domain errors are real `Exception` subclasses, so stack traces, inheritance, `except`, `except*`, and `ExceptionGroup` remain useful.
4. **No DI container.** Host frameworks decide where request context, database sessions, transactions, tenants, actors, and credentials are created.
5. **Same-process direct calls.** UseCaseAPI does not introduce HTTP, RPC, queues, or JSON serialization into the hot path.
6. **Graph-aware.** Large systems need declared usecase dependencies, graph export, Manifest catalogs, and breaking-change detection.

## The contract shape

A contract module contains:

- `{Usecase}UseCaseInput`: a Pydantic v2 model.
- `{Usecase}UseCaseOutput`: a Pydantic v2 model.
- a base domain exception derived from `UseCaseError`.
- optional leaf domain exceptions.
- a `Protocol` derived from `UseCase[{Usecase}UseCaseInput, {Usecase}UseCaseOutput]`.
- a `UseCaseRef` token created by `define_usecase`.

The `UseCaseRef` is used for binding and calling. It carries runtime metadata while preserving type information.

## Why not store metadata on the Protocol?

Putting metadata directly on the Protocol would make structural implementations appear to require those metadata attributes. UseCaseAPI keeps the Protocol pure and attaches runtime metadata to the `UseCaseRef` token instead.

## Dependency composition

UseCaseAPI does not construct dependency graphs. A binding is a function:

```python
Callable[[Caller[ContextT]], UseCase[InputT, OutputT]]
```

The host application controls the `ContextT` object. A FastAPI app may put request-scoped state there. A Django app may use middleware-created state. A worker may use job context. An AI agent runtime may use agent session context.

## Declared usecase graph

A usecase binding can declare which other usecases it may call:

```python
usecases.bind(CHECKOUT_USECASE, lambda caller: CheckoutUseCase(caller), uses=(PLACE_ORDER_USECASE,))
```

In strict mode, calling an undeclared usecase from inside a handler raises `UndeclaredUseCaseDependencyError`.

## Version identity

A contract identity is `name@vN`, for example `commerce.place_order@v1`. There is no implicit `latest`. Callers import the version they use.
