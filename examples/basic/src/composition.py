"""Composition root for the basic UseCaseAPI example application."""

from __future__ import annotations

from dataclasses import dataclass

from commerce.usecases.check_availability.v1.check_availability_contract import (
    CHECK_AVAILABILITY_USECASE,
)
from commerce.usecases.check_availability.v1.check_availability_usecase import (
    CheckAvailabilityUseCase,
    InventoryStore,
)
from commerce.usecases.checkout.v1.checkout_contract import CHECKOUT_USECASE
from commerce.usecases.checkout.v1.checkout_usecase import CheckoutUseCase
from commerce.usecases.place_order.v1.place_order_contract import PLACE_ORDER_USECASE
from commerce.usecases.place_order.v1.place_order_usecase import PlaceOrderUseCase

from usecaseapi import UseCaseAPI


@dataclass(frozen=True)
class AppContext:
    """Runtime context shared by example usecase implementations."""

    store: InventoryStore


usecases = UseCaseAPI[AppContext]()

usecases.bind(
    CHECK_AVAILABILITY_USECASE,
    lambda caller: CheckAvailabilityUseCase(caller.context.store),
)
usecases.bind(
    PLACE_ORDER_USECASE,
    lambda caller: PlaceOrderUseCase(caller.context.store),
    uses=(CHECK_AVAILABILITY_USECASE,),
)
usecases.bind(
    CHECKOUT_USECASE,
    lambda caller: CheckoutUseCase(caller),
    uses=(PLACE_ORDER_USECASE,),
)
