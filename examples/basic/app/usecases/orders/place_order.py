"""Place order implementation for the basic example."""

from __future__ import annotations

from app.contracts.orders.place_order.v1 import Input, InventoryShortage, Output, PlaceOrder
from app.usecases.inventory.check_availability import InventoryStore


class PlaceOrderImpl:
    """Implementation that accepts orders with sufficient inventory."""

    def __init__(self, store: InventoryStore) -> None:
        """Create the implementation with an inventory store."""
        self.store = store

    async def __call__(self, input: Input, /) -> Output:
        """Place an order or raise an inventory shortage error."""
        available = self.store.available(input.item.sku_id)
        if available < input.item.quantity:
            raise InventoryShortage(
                sku_id=input.item.sku_id,
                requested=input.item.quantity,
                available=available,
            )
        return Output(order_id="ord_123", status="accepted")


_impl: PlaceOrder = PlaceOrderImpl(InventoryStore({}))
