from __future__ import annotations

from typing import Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseRef, define_usecase


class Input(Model):
    sku_id: str
    quantity: int


class Output(Model):
    available: int
    ok: bool


class CheckAvailability(UseCase[Input, Output], Protocol):
    async def __call__(self, input: Input, /) -> Output: ...


CHECK_AVAILABILITY: UseCaseRef[Input, Output] = define_usecase(
    CheckAvailability,
    Contract(
        name="inventory.check_availability",
        version=1,
        input=Input,
        output=Output,
        description="Checks available inventory inside the current application process.",
    ),
)
