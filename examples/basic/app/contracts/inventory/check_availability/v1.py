"""Version 1 inventory availability contract."""

from __future__ import annotations

from typing import Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseRef, define_usecase


class Input(Model):
    """Input required to check inventory availability."""

    sku_id: str
    quantity: int


class Output(Model):
    """Inventory availability result."""

    available: int
    ok: bool


class CheckAvailability(UseCase[Input, Output], Protocol):
    """Protocol for checking inventory availability."""

    async def __call__(self, input: Input, /) -> Output:
        """Check inventory availability."""
        ...


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
