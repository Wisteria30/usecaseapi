"""Version 1 commerce inventory availability contract."""

from __future__ import annotations

from typing import Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseRef, define_usecase


class CheckAvailabilityUseCaseInput(Model):
    """Input required to check inventory availability."""

    sku_id: str
    quantity: int


class CheckAvailabilityUseCaseOutput(Model):
    """Inventory availability result."""

    available: int
    ok: bool


class CheckAvailability(
    UseCase[CheckAvailabilityUseCaseInput, CheckAvailabilityUseCaseOutput],
    Protocol,
):
    """Protocol for checking inventory availability."""

    async def __call__(
        self,
        input: CheckAvailabilityUseCaseInput,
        /,
    ) -> CheckAvailabilityUseCaseOutput:
        """Check inventory availability."""
        ...


CHECK_AVAILABILITY_USECASE: UseCaseRef[
    CheckAvailabilityUseCaseInput,
    CheckAvailabilityUseCaseOutput,
] = define_usecase(
    CheckAvailability,
    Contract(
        name="commerce.check_availability",
        version=1,
        input=CheckAvailabilityUseCaseInput,
        output=CheckAvailabilityUseCaseOutput,
        description="Checks available inventory inside the commerce package.",
    ),
)
