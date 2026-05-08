from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .api import UseCaseAPI
from .contracts import UseCaseRef
from .errors import UseCaseError


def exception_to_dict(error_type: type[UseCaseError]) -> dict[str, Any]:
    """Serialize exception class metadata for catalogs and snapshots."""

    parents: list[str] = []
    for parent in error_type.__mro__[1:]:
        if parent is Exception or parent is BaseException or parent is object:
            break
        parents.append(f"{parent.__module__}.{parent.__qualname__}")
    return {
        "type": f"{error_type.__module__}.{error_type.__qualname__}",
        "code": getattr(error_type, "code", ""),
        "parents": parents,
    }


def ref_to_dict(ref: UseCaseRef[Any, Any], *, uses: tuple[str, ...] = ()) -> dict[str, Any]:
    """Serialize a usecase reference and contract metadata."""

    contract = ref.contract
    return {
        "key": contract.key,
        "name": contract.name,
        "version": contract.version,
        "protocol": f"{ref.protocol.__module__}.{ref.protocol.__qualname__}",
        "input": {
            "type": f"{contract.input.__module__}.{contract.input.__qualname__}",
            "schema": contract.input.model_json_schema(),
        },
        "output": {
            "type": f"{contract.output.__module__}.{contract.output.__qualname__}",
            "schema": contract.output.model_json_schema(),
        },
        "raises": [exception_to_dict(error_type) for error_type in contract.raises],
        "known_errors": [exception_to_dict(error_type) for error_type in contract.known_errors],
        "stable": contract.stable,
        "deprecated": contract.deprecated,
        "superseded_by": contract.superseded_by,
        "description": contract.description,
        "tags": list(contract.tags),
        "uses": list(uses),
    }


def snapshot_from_api(api: UseCaseAPI[Any]) -> dict[str, Any]:
    """Build a JSON-serializable snapshot from a UseCaseAPI instance."""

    uses_by_key = {binding.ref.key: tuple(sorted(binding.uses)) for binding in api.bindings}
    return {
        "schema_version": 1,
        "usecases": [
            ref_to_dict(ref, uses=uses_by_key.get(ref.key, ()))
            for ref in sorted(api.contracts, key=lambda item: item.key)
        ],
    }


def write_snapshot(api: UseCaseAPI[Any], path: str | Path) -> None:
    """Write a stable JSON snapshot to disk."""

    payload = snapshot_from_api(api)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_snapshot(path: str | Path) -> dict[str, Any]:
    """Load a snapshot from disk."""

    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError("snapshot must be a JSON object")
    return cast(dict[str, Any], payload)


@dataclass(frozen=True, slots=True)
class ContractDiff:
    """Result of comparing two snapshots."""

    breaking: tuple[str, ...]
    warnings: tuple[str, ...]
    additions: tuple[str, ...]

    @property
    def has_breaking_changes(self) -> bool:
        return bool(self.breaking)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "breaking": list(self.breaking),
            "warnings": list(self.warnings),
            "additions": list(self.additions),
        }


def diff_snapshots(old: Mapping[str, Any], new: Mapping[str, Any]) -> ContractDiff:
    """Diff snapshots with conservative breaking-change detection."""

    old_cases = _index_usecases(old)
    new_cases = _index_usecases(new)
    breaking: list[str] = []
    warnings: list[str] = []
    additions: list[str] = []

    for key in sorted(set(old_cases) - set(new_cases)):
        breaking.append(f"removed usecase {key}")
    for key in sorted(set(new_cases) - set(old_cases)):
        additions.append(f"added usecase {key}")

    for key in sorted(set(old_cases) & set(new_cases)):
        old_case = old_cases[key]
        new_case = new_cases[key]
        if old_case.get("input") != new_case.get("input"):
            breaking.append(f"changed input schema for {key}")
        if old_case.get("output") != new_case.get("output"):
            breaking.append(f"changed output schema for {key}")
        old_raises = _error_codes(old_case.get("raises"))
        new_raises = _error_codes(new_case.get("raises"))
        removed_raises = sorted(old_raises - new_raises)
        if removed_raises:
            breaking.append(f"removed declared errors for {key}: {', '.join(removed_raises)}")
        old_uses = set(_string_list(old_case.get("uses")))
        new_uses = set(_string_list(new_case.get("uses")))
        removed_uses = sorted(old_uses - new_uses)
        if removed_uses:
            warnings.append(f"removed declared uses for {key}: {', '.join(removed_uses)}")
        if old_case.get("deprecated") is False and new_case.get("deprecated") is True:
            warnings.append(f"deprecated usecase {key}")
    return ContractDiff(
        breaking=tuple(breaking),
        warnings=tuple(warnings),
        additions=tuple(additions),
    )


def _index_usecases(snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    usecases = snapshot.get("usecases", [])
    if not isinstance(usecases, list):
        raise ValueError("snapshot.usecases must be a list")
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in usecases:
        if not isinstance(item, dict):
            raise ValueError("snapshot usecase must be an object")
        key = item.get("key")
        if not isinstance(key, str):
            raise ValueError("snapshot usecase key must be a string")
        indexed[key] = item
    return indexed


def _error_codes(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    codes: set[str] = set()
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("code"), str):
            codes.add(cast(str, item["code"]))
    return codes


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
