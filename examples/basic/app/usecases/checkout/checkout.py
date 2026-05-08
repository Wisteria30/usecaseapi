from __future__ import annotations

from typing import TYPE_CHECKING

from usecaseapi import Caller

if TYPE_CHECKING:
    from app.composition import AppContext
from app.contracts.checkout.checkout.v1 import Checkout, Input, Output
from app.contracts.orders.place_order.v1 import PLACE_ORDER, Item
from app.contracts.orders.place_order.v1 import Input as PlaceOrderInput


class CheckoutImpl:
    def __init__(self, caller: Caller[AppContext]) -> None:
        self.caller = caller

    async def __call__(self, input: Input, /) -> Output:
        placed = await self.caller.call(
            PLACE_ORDER,
            PlaceOrderInput(
                user_id=input.user_id,
                item=Item(sku_id=input.sku_id, quantity=input.quantity),
            ),
        )
        return Output(order_id=placed.order_id)


_impl: Checkout
