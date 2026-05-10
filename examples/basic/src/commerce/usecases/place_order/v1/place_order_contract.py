"""Version 1 commerce place order contract."""

from __future__ import annotations

from typing import ClassVar, Literal, Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseError, UseCaseRef, define_usecase


class Item(Model):
    """Order item requested by the caller."""

    sku_id: str
    quantity: int


class PlaceOrderUseCaseInput(Model):
    """Input required to place an order."""

    user_id: str
    item: Item


class PlaceOrderUseCaseOutput(Model):
    """Accepted order result."""

    order_id: str
    status: Literal["accepted"]


class PlaceOrderError(UseCaseError):
    """Base error for place order failures."""

    code: ClassVar[str] = "commerce.place_order"


class InventoryShortage(PlaceOrderError):
    """Raised when requested inventory is unavailable."""

    code: ClassVar[str] = "commerce.place_order.inventory_shortage"

    def __init__(self, *, sku_id: str, requested: int, available: int) -> None:
        """Create an inventory shortage error with requested and available quantities."""
        self.sku_id = sku_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"inventory shortage: sku_id={sku_id}, requested={requested}, available={available}"
        )


class PlaceOrder(UseCase[PlaceOrderUseCaseInput, PlaceOrderUseCaseOutput], Protocol):
    """Protocol for placing an order."""

    async def __call__(self, input: PlaceOrderUseCaseInput, /) -> PlaceOrderUseCaseOutput:
        """Place an order."""
        ...


PLACE_ORDER_USECASE: UseCaseRef[PlaceOrderUseCaseInput, PlaceOrderUseCaseOutput] = define_usecase(
    PlaceOrder,
    Contract(
        name="commerce.place_order",
        version=1,
        input=PlaceOrderUseCaseInput,
        output=PlaceOrderUseCaseOutput,
        raises=(PlaceOrderError,),
        known_errors=(InventoryShortage,),
        description="Creates an order after inventory has been confirmed.",
    ),
)
