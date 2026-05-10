"""Version 1 commerce checkout workflow contract."""

from __future__ import annotations

from typing import Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseRef, define_usecase


class CheckoutUseCaseInput(Model):
    """Input required to run checkout."""

    user_id: str
    sku_id: str
    quantity: int


class CheckoutUseCaseOutput(Model):
    """Checkout result returned to callers."""

    order_id: str


class Checkout(UseCase[CheckoutUseCaseInput, CheckoutUseCaseOutput], Protocol):
    """Protocol for the checkout workflow."""

    async def __call__(self, input: CheckoutUseCaseInput, /) -> CheckoutUseCaseOutput:
        """Run checkout."""
        ...


CHECKOUT_USECASE: UseCaseRef[CheckoutUseCaseInput, CheckoutUseCaseOutput] = define_usecase(
    Checkout,
    Contract(
        name="commerce.checkout",
        version=1,
        input=CheckoutUseCaseInput,
        output=CheckoutUseCaseOutput,
        description="Workflow-style usecase that composes other usecases in-process.",
    ),
)
