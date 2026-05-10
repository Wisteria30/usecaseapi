"""Tests for commerce.check_availability v1."""

from __future__ import annotations

from commerce.usecases.check_availability.v1.check_availability_contract import (
    CHECK_AVAILABILITY_USECASE,
    CheckAvailability,
)
from commerce.usecases.check_availability.v1.check_availability_usecase import (
    CheckAvailabilityUseCase,
    InventoryStore,
)


def test_check_availability_contract_metadata() -> None:
    """Contract metadata matches the scaffolded usecase identity."""
    assert CHECK_AVAILABILITY_USECASE.contract.name == "commerce.check_availability"
    assert CHECK_AVAILABILITY_USECASE.contract.version == 1


def test_check_availability_usecase_matches_contract() -> None:
    """Usecase implementation structurally matches the contract Protocol."""
    usecase: CheckAvailability = CheckAvailabilityUseCase(InventoryStore({}))
    assert usecase.__class__ is CheckAvailabilityUseCase
