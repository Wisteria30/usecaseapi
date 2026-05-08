from __future__ import annotations

from app.contracts.orders.place_order.v1 import Input, InventoryShortage, Output, PlaceOrder
from app.usecases.inventory.check_availability import InventoryStore


class PlaceOrderImpl:
    def __init__(self, store: InventoryStore) -> None:
        self.store = store

    async def __call__(self, input: Input, /) -> Output:
        available = self.store.available(input.item.sku_id)
        if available < input.item.quantity:
            raise InventoryShortage(
                sku_id=input.item.sku_id,
                requested=input.item.quantity,
                available=available,
            )
        return Output(order_id="ord_123", status="accepted")


_impl: PlaceOrder = PlaceOrderImpl(InventoryStore({}))
