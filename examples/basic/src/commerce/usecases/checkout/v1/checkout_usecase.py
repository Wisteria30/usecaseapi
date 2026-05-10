"""Checkout workflow implementation for the basic commerce example."""

from __future__ import annotations

from typing import TYPE_CHECKING

from commerce.usecases.checkout.v1.checkout_contract import (
    CheckoutUseCaseInput,
    CheckoutUseCaseOutput,
)
from commerce.usecases.place_order.v1.place_order_contract import (
    PLACE_ORDER_USECASE,
    Item,
    PlaceOrderUseCaseInput,
)
from usecaseapi import Caller

if TYPE_CHECKING:
    from composition import AppContext


class CheckoutUseCase:
    """Implementation that composes order placement inside the commerce package."""

    def __init__(self, caller: Caller[AppContext]) -> None:
        """Create the implementation with a context-bound caller."""
        self.caller = caller

    async def __call__(self, input: CheckoutUseCaseInput, /) -> CheckoutUseCaseOutput:
        """Run checkout by delegating to the place order usecase."""
        placed = await self.caller.call(
            PLACE_ORDER_USECASE,
            PlaceOrderUseCaseInput(
                user_id=input.user_id,
                item=Item(sku_id=input.sku_id, quantity=input.quantity),
            ),
        )
        return CheckoutUseCaseOutput(order_id=placed.order_id)
