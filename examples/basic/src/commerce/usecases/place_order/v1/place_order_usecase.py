"""Place order implementation for the basic commerce example."""

from __future__ import annotations

from commerce.usecases.check_availability.v1.check_availability_usecase import InventoryStore
from commerce.usecases.place_order.v1.place_order_contract import (
    InventoryShortage,
    PlaceOrderUseCaseInput,
    PlaceOrderUseCaseOutput,
)


class PlaceOrderUseCase:
    """Implementation that accepts purchase requests with sufficient inventory."""

    def __init__(self, store: InventoryStore) -> None:
        """Create the implementation with an inventory store."""
        self.store = store

    async def __call__(self, input: PlaceOrderUseCaseInput, /) -> PlaceOrderUseCaseOutput:
        """Place an order or raise an inventory shortage error."""
        available = self.store.available(input.item.sku_id)
        if available < input.item.quantity:
            raise InventoryShortage(
                sku_id=input.item.sku_id,
                requested=input.item.quantity,
                available=available,
            )
        return PlaceOrderUseCaseOutput(order_id="ord_123", status="accepted")
