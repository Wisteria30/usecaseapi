from __future__ import annotations

from typing import Any

from .api import UseCaseAPI
from .contracts import UseCaseRef


def render_markdown(api: UseCaseAPI[Any]) -> str:
    """Render registered usecases as human-readable Markdown."""

    bindings = {binding.ref.key: binding for binding in api.bindings}
    lines: list[str] = ["# UseCaseAPI Contracts", ""]
    for ref in sorted(api.contracts, key=lambda item: item.key):
        contract = ref.contract
        lines.extend(
            [
                f"## {contract.name} v{contract.version}",
                "",
                f"Key: `{contract.key}`",
                f"Protocol: `{ref.protocol.__module__}.{ref.protocol.__qualname__}`",
                f"Input: `{contract.input.__module__}.{contract.input.__qualname__}`",
                f"Output: `{contract.output.__module__}.{contract.output.__qualname__}`",
                f"Stable: `{contract.stable}`",
                f"Deprecated: `{contract.deprecated}`",
            ]
        )
        if contract.superseded_by:
            lines.append(f"Superseded by: `{contract.superseded_by}`")
        if contract.description:
            lines.extend(["", contract.description])
        lines.extend(["", "### Raises", ""])
        if contract.raises:
            for error_type in contract.raises:
                lines.append(
                    f"- `{error_type.__module__}.{error_type.__qualname__}` "
                    f"(`{getattr(error_type, 'code', '')}`)"
                )
        else:
            lines.append("- None declared")
        if contract.known_errors:
            lines.extend(["", "### Known leaf errors", ""])
            for error_type in contract.known_errors:
                lines.append(
                    f"- `{error_type.__module__}.{error_type.__qualname__}` "
                    f"(`{getattr(error_type, 'code', '')}`)"
                )
        lines.extend(["", "### Declared uses", ""])
        binding = bindings.get(ref.key)
        if binding is not None and binding.uses:
            for use_key in sorted(binding.uses):
                lines.append(f"- `{use_key}`")
        else:
            lines.append("- None")
        lines.extend(["", "### Input fields", ""])
        _append_model_fields(lines, ref, kind="input")
        lines.extend(["", "### Output fields", ""])
        _append_model_fields(lines, ref, kind="output")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_mermaid(api: UseCaseAPI[Any]) -> str:
    """Render declared usecase dependencies as a Mermaid graph."""

    lines = ["flowchart TD"]
    for ref in sorted(api.contracts, key=lambda item: item.key):
        node = _node_id(ref.key)
        lines.append(f'  {node}["{ref.key}"]')
    for binding in sorted(api.bindings, key=lambda item: item.ref.key):
        source = _node_id(binding.ref.key)
        for use_key in sorted(binding.uses):
            lines.append(f"  {source} --> {_node_id(use_key)}")
    return "\n".join(lines) + "\n"


def _append_model_fields(lines: list[str], ref: UseCaseRef[Any, Any], *, kind: str) -> None:
    model_type = ref.contract.input if kind == "input" else ref.contract.output
    if not model_type.model_fields:
        lines.append("- No fields")
        return
    for name, field in model_type.model_fields.items():
        annotation = field.annotation
        lines.append(f"- `{name}`: `{annotation!r}`")


def _node_id(key: str) -> str:
    return "uc_" + "".join(character if character.isalnum() else "_" for character in key)
