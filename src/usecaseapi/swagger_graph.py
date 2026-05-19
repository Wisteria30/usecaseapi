"""Graph resolution for development-only Swagger preview support."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .api import Binding, UseCaseAPI


@dataclass(frozen=True, slots=True)
class PreviewGraph:
    """Immutable dependency graph for one preview composition."""

    target: str
    api: UseCaseAPI[Any]
    create_context: Callable[..., Any] | None
    nodes: frozenset[str]
    edges: frozenset[tuple[str, str]]
    children_by_parent: Mapping[str, frozenset[str]]
    parents_by_child: Mapping[str, frozenset[str]]
    roots: frozenset[str]
    binding_by_key: Mapping[str, Binding[Any]]


def build_preview_graph(
    *,
    target: str,
    api: UseCaseAPI[Any],
    create_context: Callable[..., Any] | None,
) -> PreviewGraph:
    """Build a dependency graph from one UseCaseAPI composition."""
    api.validate(require_handlers=True)
    binding_by_key = {binding.ref.key: binding for binding in api.bindings}
    nodes = frozenset(binding_by_key)
    edges = frozenset(
        (binding.ref.key, used_key)
        for binding in api.bindings
        for used_key in binding.uses
    )

    mutable_children: dict[str, set[str]] = {key: set() for key in nodes}
    mutable_parents: dict[str, set[str]] = {key: set() for key in nodes}
    for parent, child in edges:
        mutable_children[parent].add(child)
        mutable_parents[child].add(parent)

    children_by_parent = {
        key: frozenset(children) for key, children in mutable_children.items()
    }
    parents_by_child = {key: frozenset(parents) for key, parents in mutable_parents.items()}
    roots = frozenset(key for key, parents in parents_by_child.items() if not parents)

    return PreviewGraph(
        target=target,
        api=api,
        create_context=create_context,
        nodes=nodes,
        edges=edges,
        children_by_parent=MappingProxyType(children_by_parent),
        parents_by_child=MappingProxyType(parents_by_child),
        roots=roots,
        binding_by_key=MappingProxyType(binding_by_key),
    )
