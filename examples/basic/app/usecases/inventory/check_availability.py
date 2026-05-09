"""Inventory availability implementation for the basic example."""

from __future__ import annotations

from app.contracts.inventory.check_availability.v1 import CheckAvailability, Input, Output


class InventoryStore:
    """In-memory inventory store used by the example."""

    def __init__(self, stock: dict[str, int]) -> None:
        """Create a store with stock quantities by SKU."""
        self.stock = stock

    def available(self, sku_id: str) -> int:
        """Return the available quantity for a SKU."""
        return self.stock.get(sku_id, 0)


class CheckAvailabilityImpl:
    """Implementation that checks available inventory."""

    def __init__(self, store: InventoryStore) -> None:
        """Create the implementation with an inventory store."""
        self.store = store

    async def __call__(self, input: Input, /) -> Output:
        """Check whether requested inventory is available."""
        available = self.store.available(input.sku_id)
        return Output(available=available, ok=available >= input.quantity)


_impl: CheckAvailability = CheckAvailabilityImpl(InventoryStore({}))
