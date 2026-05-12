"""Public package exports for UseCaseAPI."""

from __future__ import annotations

from .api import Binding, Caller, CallRecord, UseCaseAPI
from .contracts import Contract, UseCase, UseCaseRef, define_usecase
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
from .manifest import (
    MANIFEST_EXTENSION,
    MANIFEST_KIND,
    MANIFEST_MEDIA_TYPE,
    MANIFEST_PROFILE_KIND,
    ManifestDiff,
    ManifestError,
    ManifestScaffoldResult,
    diff_manifest_with_api,
    diff_manifests,
    dump_manifest,
    load_manifest,
    manifest_from_api,
    manifest_to_yaml,
    render_manifest_graph,
    render_manifest_markdown,
    scaffold_from_manifest,
    validate_manifest,
)
from .model import Model
from .scaffold import ScaffoldOptions, ScaffoldResult, scaffold_usecase

__all__ = [
    "Binding",
    "CallRecord",
    "Caller",
    "Contract",
    "ContractDefinitionError",
    "DuplicateUseCaseError",
    "InvalidHandlerError",
    "MANIFEST_EXTENSION",
    "MANIFEST_KIND",
    "MANIFEST_MEDIA_TYPE",
    "MANIFEST_PROFILE_KIND",
    "ManifestDiff",
    "ManifestError",
    "ManifestScaffoldResult",
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
    "diff_manifest_with_api",
    "diff_manifests",
    "dump_manifest",
    "load_manifest",
    "manifest_from_api",
    "manifest_to_yaml",
    "render_manifest_graph",
    "render_manifest_markdown",
    "scaffold_from_manifest",
    "scaffold_usecase",
    "validate_manifest",
]
