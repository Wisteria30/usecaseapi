from __future__ import annotations

from typing import Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseRef, define_usecase


class Input(Model):
    user_id: str
    sku_id: str
    quantity: int


class Output(Model):
    order_id: str


class Checkout(UseCase[Input, Output], Protocol):
    async def __call__(self, input: Input, /) -> Output: ...


CHECKOUT: UseCaseRef[Input, Output] = define_usecase(
    Checkout,
    Contract(
        name="checkout.checkout",
        version=1,
        input=Input,
        output=Output,
        description="Workflow-style usecase that composes other usecases in-process.",
    ),
)
