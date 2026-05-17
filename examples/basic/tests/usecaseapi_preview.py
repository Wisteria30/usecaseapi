"""Swagger preview configuration for the basic commerce example."""

from __future__ import annotations

import sys

from pathlib import Path

from fastapi import Request

from usecaseapi.swagger import SwaggerPreviewError

_EXAMPLE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_EXAMPLE_SRC) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE_SRC))

from commerce.usecases.check_availability.v1.check_availability_usecase import (  # noqa: E402
    InventoryStore,
)
from composition import AppContext, usecases  # noqa: E402

api = usecases

_STOCK_BY_SCENARIO = {
    "default": {"sku_456": 10, "sku_sold_out": 0},
    "empty": {"sku_456": 0, "sku_sold_out": 0},
    "rich": {"sku_456": 100, "sku_sold_out": 5},
}


async def create_context(request: Request) -> AppContext:
    """Create a preview context from the requested inventory scenario."""
    scenario = request.headers.get("x-usecaseapi-scenario", "default")
    if scenario not in _STOCK_BY_SCENARIO:
        supported = ", ".join(sorted(_STOCK_BY_SCENARIO))
        raise SwaggerPreviewError(
            f"unknown x-usecaseapi-scenario value {scenario!r}; supported values: {supported}"
        )
    return AppContext(store=InventoryStore(_STOCK_BY_SCENARIO[scenario]))
