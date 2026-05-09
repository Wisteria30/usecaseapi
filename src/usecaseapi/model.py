"""Pydantic model base class exported by UseCaseAPI."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Model(BaseModel):
    """Base model for UseCaseAPI input and output objects.

    The default configuration is intentionally strict and immutable-ish:
    unknown fields are rejected and model instances are frozen.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)
