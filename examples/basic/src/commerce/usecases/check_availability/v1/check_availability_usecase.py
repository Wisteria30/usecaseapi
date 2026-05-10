"""Inventory availability implementation for the basic commerce example."""

from __future__ import annotations

from commerce.usecases.check_availability.v1.check_availability_contract import (
    CheckAvailabilityUseCaseInput,
    CheckAvailabilityUseCaseOutput,
)


class InventoryStore:
    """In-memory inventory store used by the example."""

    def __init__(self, stock: dict[str, int]) -> None:
        """Create a store with stock quantities by SKU."""
        self.stock = stock

    def available(self, sku_id: str) -> int:
        """Return the available quantity for a SKU."""
        return self.stock.get(sku_id, 0)


class CheckAvailabilityUseCase:
    """Implementation that checks available inventory."""

    def __init__(self, store: InventoryStore) -> None:
        """Create the implementation with an inventory store."""
        self.store = store

    async def __call__(
        self,
        input: CheckAvailabilityUseCaseInput,
        /,
    ) -> CheckAvailabilityUseCaseOutput:
        """Check whether requested inventory is available."""
        available = self.store.available(input.sku_id)
        return CheckAvailabilityUseCaseOutput(available=available, ok=available >= input.quantity)
