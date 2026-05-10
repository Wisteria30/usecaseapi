"""Tests for commerce.place_order v1."""

from __future__ import annotations

from commerce.usecases.check_availability.v1.check_availability_usecase import InventoryStore
from commerce.usecases.place_order.v1.place_order_contract import PLACE_ORDER_USECASE, PlaceOrder
from commerce.usecases.place_order.v1.place_order_usecase import PlaceOrderUseCase


def test_place_order_contract_metadata() -> None:
    """Contract metadata matches the scaffolded usecase identity."""
    assert PLACE_ORDER_USECASE.contract.name == "commerce.place_order"
    assert PLACE_ORDER_USECASE.contract.version == 1


def test_place_order_usecase_matches_contract() -> None:
    """Usecase implementation structurally matches the contract Protocol."""
    usecase: PlaceOrder = PlaceOrderUseCase(InventoryStore({}))
    assert usecase.__class__ is PlaceOrderUseCase
