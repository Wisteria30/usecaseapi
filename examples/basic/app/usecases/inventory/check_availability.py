from __future__ import annotations

from app.contracts.inventory.check_availability.v1 import CheckAvailability, Input, Output


class InventoryStore:
    def __init__(self, stock: dict[str, int]) -> None:
        self.stock = stock

    def available(self, sku_id: str) -> int:
        return self.stock.get(sku_id, 0)


class CheckAvailabilityImpl:
    def __init__(self, store: InventoryStore) -> None:
        self.store = store

    async def __call__(self, input: Input, /) -> Output:
        available = self.store.available(input.sku_id)
        return Output(available=available, ok=available >= input.quantity)


_impl: CheckAvailability = CheckAvailabilityImpl(InventoryStore({}))
