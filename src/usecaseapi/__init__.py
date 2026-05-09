"""Public package exports for UseCaseAPI."""

from __future__ import annotations

from .api import Binding, Caller, CallRecord, UseCaseAPI
from .contracts import Contract, UseCase, UseCaseRef, define_usecase
from .docs import render_markdown, render_mermaid
from .errors import (
    ContractDefinitionError,
    DuplicateUseCaseError,
    InvalidHandlerError,
    MissingBindingError,
    UndeclaredUseCaseDependencyError,
    UndeclaredUseCaseError,
    UseCaseAPIError,
    UseCaseError,
)
from .model import Model
from .scaffold import ScaffoldOptions, ScaffoldResult, scaffold_usecase
from .snapshot import ContractDiff, diff_snapshots, load_snapshot, snapshot_from_api, write_snapshot

__all__ = [
    "Binding",
    "CallRecord",
    "Caller",
    "Contract",
    "ContractDefinitionError",
    "ContractDiff",
    "DuplicateUseCaseError",
    "InvalidHandlerError",
    "MissingBindingError",
    "Model",
    "ScaffoldOptions",
    "ScaffoldResult",
    "UndeclaredUseCaseDependencyError",
    "UndeclaredUseCaseError",
    "UseCase",
    "UseCaseAPI",
    "UseCaseAPIError",
    "UseCaseError",
    "UseCaseRef",
    "define_usecase",
    "diff_snapshots",
    "load_snapshot",
    "render_markdown",
    "render_mermaid",
    "scaffold_usecase",
    "snapshot_from_api",
    "write_snapshot",
]
