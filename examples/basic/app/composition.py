from __future__ import annotations

from dataclasses import dataclass

from app.contracts.checkout.checkout.v1 import CHECKOUT
from app.contracts.inventory.check_availability.v1 import CHECK_AVAILABILITY
from app.contracts.orders.place_order.v1 import PLACE_ORDER
from app.usecases.checkout.checkout import CheckoutImpl
from app.usecases.inventory.check_availability import CheckAvailabilityImpl, InventoryStore
from app.usecases.orders.place_order import PlaceOrderImpl
from usecaseapi import UseCaseAPI


@dataclass(frozen=True)
class AppContext:
    store: InventoryStore


usecases = UseCaseAPI[AppContext]()

usecases.bind(
    CHECK_AVAILABILITY,
    lambda caller: CheckAvailabilityImpl(caller.context.store),
)
usecases.bind(
    PLACE_ORDER,
    lambda caller: PlaceOrderImpl(caller.context.store),
    uses=(CHECK_AVAILABILITY,),
)
usecases.bind(
    CHECKOUT,
    lambda caller: CheckoutImpl(caller),
    uses=(PLACE_ORDER,),
)
