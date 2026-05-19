"""Graph resolution for development-only Swagger preview support."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .api import Binding, UseCaseAPI
from .errors import UseCaseAPIError


class SwaggerGraphError(UseCaseAPIError):
    """Raised when preview dependency graphs cannot be resolved."""


@dataclass(frozen=True, slots=True)
class BindingIdentity:
    """Stable metadata for comparing preview graph bindings."""

    factory_id: int
    factory_module: str
    factory_qualname: str


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
    binding_identity_by_key: Mapping[str, BindingIdentity]


def binding_identity(factory: Callable[..., Any]) -> BindingIdentity:
    """Return identity metadata for a binding factory."""
    factory_type = type(factory)
    module = getattr(factory, "__module__", factory_type.__module__)
    qualname = getattr(factory, "__qualname__", factory_type.__qualname__)
    return BindingIdentity(
        factory_id=id(factory),
        factory_module=str(module),
        factory_qualname=str(qualname),
    )


def build_preview_graph(
    *,
    target: str,
    api: UseCaseAPI[Any],
    create_context: Callable[..., Any] | None,
) -> PreviewGraph:
    """Build a dependency graph from one UseCaseAPI composition."""
    api.validate(require_handlers=True)
    binding_by_key = {binding.ref.key: binding for binding in api.bindings}
    binding_identity_by_key = {
        key: binding_identity(binding.factory) for key, binding in binding_by_key.items()
    }
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

    graph = PreviewGraph(
        target=target,
        api=api,
        create_context=create_context,
        nodes=nodes,
        edges=edges,
        children_by_parent=MappingProxyType(children_by_parent),
        parents_by_child=MappingProxyType(parents_by_child),
        roots=roots,
        binding_by_key=MappingProxyType(binding_by_key),
        binding_identity_by_key=MappingProxyType(binding_identity_by_key),
    )
    require_acyclic(graph)
    return graph


def detect_cycle(graph: PreviewGraph) -> tuple[str, ...] | None:
    """Return a cycle path if the graph contains one."""
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> tuple[str, ...] | None:
        if node in visiting:
            index = stack.index(node)
            return (*stack[index:], node)
        if node in visited:
            return None

        visiting.add(node)
        stack.append(node)
        for child in sorted(graph.children_by_parent[node]):
            cycle = visit(child)
            if cycle is not None:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(graph.nodes):
        cycle = visit(node)
        if cycle is not None:
            return cycle
    return None


def require_acyclic(graph: PreviewGraph) -> None:
    """Reject cyclic dependency graphs because root grouping would be ambiguous."""
    cycle = detect_cycle(graph)
    if cycle is None:
        return

    raise SwaggerGraphError(
        "dependency cycle detected in " f"{graph.target}: " + " -> ".join(cycle)
    )


def reachable_nodes_by_root(graph: PreviewGraph) -> dict[str, frozenset[str]]:
    """Return every node reachable from each root use case."""
    memo: dict[str, frozenset[str]] = {}

    def descend(node: str) -> frozenset[str]:
        cached = memo.get(node)
        if cached is not None:
            return cached

        reachable = {node}
        for child in graph.children_by_parent[node]:
            reachable.update(descend(child))
        result = frozenset(reachable)
        memo[node] = result
        return result

    return {root: descend(root) for root in sorted(graph.roots)}


def graph_contains(parent: PreviewGraph, child: PreviewGraph) -> bool:
    """Return whether one graph fully contains another visible graph."""
    if parent is child:
        return False
    if not child.nodes <= parent.nodes:
        return False
    if not child.edges <= parent.edges:
        return False
    if parent.create_context is not child.create_context:
        return False
    return all(
        parent.binding_identity_by_key[node] == child.binding_identity_by_key[node]
        for node in child.nodes
    )


def resolve_visible_graphs(graphs: list[PreviewGraph]) -> list[PreviewGraph]:
    """Return deterministic graphs after removing contained subgraphs."""
    sorted_graphs = sorted(graphs, key=lambda graph: graph.target)
    return [
        graph
        for graph in sorted_graphs
        if not any(graph_contains(parent, graph) for parent in sorted_graphs)
    ]
