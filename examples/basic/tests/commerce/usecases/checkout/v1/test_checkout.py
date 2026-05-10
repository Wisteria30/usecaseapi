"""Tests for commerce.checkout v1."""

from __future__ import annotations

from typing import Any, cast

from commerce.usecases.checkout.v1.checkout_contract import CHECKOUT_USECASE, Checkout
from commerce.usecases.checkout.v1.checkout_usecase import CheckoutUseCase


def test_checkout_contract_metadata() -> None:
    """Contract metadata matches the scaffolded usecase identity."""
    assert CHECKOUT_USECASE.contract.name == "commerce.checkout"
    assert CHECKOUT_USECASE.contract.version == 1


def test_checkout_usecase_matches_contract() -> None:
    """Usecase implementation structurally matches the contract Protocol."""
    usecase: Checkout = CheckoutUseCase(cast(Any, object()))
    assert usecase.__class__ is CheckoutUseCase
