"""Runtime call behavior tests."""

from __future__ import annotations

import asyncio

from typing import ClassVar, Protocol

import pytest

from usecaseapi import (
    Contract,
    Model,
    UndeclaredUseCaseDependencyError,
    UndeclaredUseCaseError,
    UseCase,
    UseCaseAPI,
    UseCaseError,
    UseCaseRef,
    define_usecase,
)


class Input(Model):
    value: int


class Output(Model):
    value: int


class ExampleError(UseCaseError):
    code: ClassVar[str] = "example"


class KnownExampleError(ExampleError):
    code: ClassVar[str] = "example.known"

    def __init__(self) -> None:
        """Create a known example error."""
        super().__init__("known")


class OtherError(UseCaseError):
    code: ClassVar[str] = "other"

    def __init__(self) -> None:
        """Create an undeclared example error."""
        super().__init__("other")


class Example(UseCase[Input, Output], Protocol):
    async def __call__(self, input: Input, /) -> Output: ...


EXAMPLE: UseCaseRef[Input, Output] = define_usecase(
    Example,
    Contract(
        name="example.run",
        version=1,
        input=Input,
        output=Output,
        raises=(ExampleError,),
        known_errors=(KnownExampleError,),
    ),
)


class Context(Model):
    multiplier: int


class GoodImpl:
    def __init__(self, multiplier: int) -> None:
        """Create an implementation with a multiplier."""
        self.multiplier = multiplier

    async def __call__(self, input: Input, /) -> Output:
        return Output(value=input.value * self.multiplier)


class KnownErrorImpl:
    async def __call__(self, input: Input, /) -> Output:
        raise KnownExampleError


class OtherErrorImpl:
    async def __call__(self, input: Input, /) -> Output:
        raise OtherError


def test_direct_call_uses_context_and_returns_output() -> None:
    """A direct call uses caller context and returns the handler output."""
    api = UseCaseAPI[Context]()
    api.bind(EXAMPLE, lambda caller: GoodImpl(caller.context.multiplier))

    output = asyncio.run(api.caller(Context(multiplier=3)).call(EXAMPLE, Input(value=7)))

    assert output == Output(value=21)


def test_declared_domain_error_is_propagated() -> None:
    """Declared domain errors propagate unchanged."""
    api = UseCaseAPI[Context]()
    api.bind(EXAMPLE, lambda caller: KnownErrorImpl())

    with pytest.raises(KnownExampleError):
        asyncio.run(api.caller(Context(multiplier=1)).call(EXAMPLE, Input(value=7)))


def test_undeclared_domain_error_is_wrapped_as_contract_violation() -> None:
    """Undeclared domain errors are wrapped as contract violations."""
    api = UseCaseAPI[Context]()
    api.bind(EXAMPLE, lambda caller: OtherErrorImpl())

    with pytest.raises(UndeclaredUseCaseError):
        asyncio.run(api.caller(Context(multiplier=1)).call(EXAMPLE, Input(value=7)))


def test_strict_declared_uses_guard() -> None:
    """Strict dependency mode rejects undeclared nested usecase calls."""
    class Parent(UseCase[Input, Output], Protocol):
        async def __call__(self, input: Input, /) -> Output: ...

    PARENT: UseCaseRef[Input, Output] = define_usecase(
        Parent,
        Contract(name="parent.run", version=1, input=Input, output=Output),
    )

    class ParentImpl:
        def __init__(self, api_caller: object) -> None:
            self.api_caller = api_caller

        async def __call__(self, input: Input, /) -> Output:
            from usecaseapi import Caller

            caller = self.api_caller
            assert isinstance(caller, Caller)
            return await caller.call(EXAMPLE, input)

    api = UseCaseAPI[Context]()
    api.bind(PARENT, lambda caller: ParentImpl(caller))
    api.bind(EXAMPLE, lambda caller: GoodImpl(2))

    with pytest.raises(UndeclaredUseCaseDependencyError):
        asyncio.run(api.caller(Context(multiplier=1)).call(PARENT, Input(value=7)))

    api.bind(PARENT, lambda caller: ParentImpl(caller), uses=(EXAMPLE,), replace=True)
    output = asyncio.run(api.caller(Context(multiplier=1)).call(PARENT, Input(value=7)))
    assert output == Output(value=14)
