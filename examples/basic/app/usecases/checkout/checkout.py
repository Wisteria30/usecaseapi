"""Checkout workflow implementation for the basic example."""

from __future__ import annotations

from typing import TYPE_CHECKING

from usecaseapi import Caller

if TYPE_CHECKING:
    from app.composition import AppContext
from app.contracts.checkout.checkout.v1 import Checkout, Input, Output
from app.contracts.orders.place_order.v1 import (
    PLACE_ORDER,
    Input as PlaceOrderInput,
    Item,
)


class CheckoutImpl:
    """Implementation that composes order placement."""

    def __init__(self, caller: Caller[AppContext]) -> None:
        """Create the implementation with a context-bound caller."""
        self.caller = caller

    async def __call__(self, input: Input, /) -> Output:
        """Run checkout by delegating to the place order usecase."""
        placed = await self.caller.call(
            PLACE_ORDER,
            PlaceOrderInput(
                user_id=input.user_id,
                item=Item(sku_id=input.sku_id, quantity=input.quantity),
            ),
        )
        return Output(order_id=placed.order_id)


_impl: Checkout
