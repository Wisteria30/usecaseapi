"""Swagger preview graph tests."""

from __future__ import annotations

from typing import Protocol

import pytest

from usecaseapi import Contract, Model, UseCaseAPI, define_usecase
from usecaseapi.errors import MissingBindingError
from usecaseapi.swagger_graph import (
    SwaggerGraphError,
    build_preview_graph,
    reachable_nodes_by_root,
    resolve_visible_graphs,
    route_groups_for_graphs,
)


class Input(Model):
    value: int


class Output(Model):
    value: int


class ParentUseCase(Protocol):
    async def __call__(self, input: Input) -> Output: ...


class ChildUseCase(Protocol):
    async def __call__(self, input: Input) -> Output: ...


class LeafUseCase(Protocol):
    async def __call__(self, input: Input) -> Output: ...


PARENT = define_usecase(
    ParentUseCase,
    Contract(name="commerce.checkout", version=1, input=Input, output=Output),
)
CHILD = define_usecase(
    ChildUseCase,
    Contract(name="commerce.place_order", version=1, input=Input, output=Output),
)
LEAF = define_usecase(
    LeafUseCase,
    Contract(name="commerce.check_availability", version=1, input=Input, output=Output),
)


class Handler:
    async def __call__(self, input: Input) -> Output:
        return Output(value=input.value)


def bind_graph_api() -> UseCaseAPI[None]:
    """Bind a three-node dependency graph for preview tests."""
    api = UseCaseAPI[None]()
    api.bind(PARENT, lambda caller: Handler(), uses=(CHILD,))
    api.bind(CHILD, lambda caller: Handler(), uses=(LEAF,))
    api.bind(LEAF, lambda caller: Handler())
    return api


def test_build_preview_graph_uses_declared_dependencies() -> None:
    """Build graph edges from declared binding dependencies."""
    given_api = bind_graph_api()

    graph = build_preview_graph(target="composition", api=given_api, create_context=None)

    assert graph.target == "composition"
    assert graph.nodes == frozenset({PARENT.key, CHILD.key, LEAF.key})
    assert graph.edges == frozenset({(PARENT.key, CHILD.key), (CHILD.key, LEAF.key)})
    assert graph.children_by_parent == {
        PARENT.key: frozenset({CHILD.key}),
        CHILD.key: frozenset({LEAF.key}),
        LEAF.key: frozenset(),
    }
    assert graph.parents_by_child == {
        PARENT.key: frozenset(),
        CHILD.key: frozenset({PARENT.key}),
        LEAF.key: frozenset({CHILD.key}),
    }
    assert graph.roots == frozenset({PARENT.key})


def test_build_preview_graph_rejects_missing_dependency_binding() -> None:
    """Reject graphs with declared dependencies that are not bound."""
    given_api = UseCaseAPI[None]()
    given_api.bind(PARENT, lambda caller: Handler(), uses=(CHILD,))

    with pytest.raises(MissingBindingError, match=CHILD.key):
        build_preview_graph(target="composition", api=given_api, create_context=None)


def test_build_preview_graph_rejects_dependency_cycles() -> None:
    """Reject dependency graphs that contain cycles."""
    given_api = UseCaseAPI[None]()
    given_api.bind(PARENT, lambda caller: Handler(), uses=(CHILD,))
    given_api.bind(CHILD, lambda caller: Handler(), uses=(PARENT,))

    with pytest.raises(SwaggerGraphError, match="dependency cycle detected"):
        build_preview_graph(target="composition", api=given_api, create_context=None)


def test_reachable_nodes_by_root_memoizes_dependency_flows() -> None:
    """Resolve every node reachable from each graph root."""
    graph = build_preview_graph(target="composition", api=bind_graph_api(), create_context=None)

    reachable = reachable_nodes_by_root(graph)

    assert reachable == {
        PARENT.key: frozenset({PARENT.key, CHILD.key, LEAF.key}),
    }


def test_resolve_visible_graphs_collapses_true_subgraphs() -> None:
    """Hide graphs fully contained by a larger graph with the same bindings."""
    parent_api = bind_graph_api()
    child_api = UseCaseAPI[None]()
    child_api.bind(CHILD, parent_api.binding_for_key(CHILD.key).factory, uses=(LEAF,))
    child_api.bind(LEAF, parent_api.binding_for_key(LEAF.key).factory)
    parent = build_preview_graph(target="app.composition", api=parent_api, create_context=None)
    child = build_preview_graph(target="commerce.composition", api=child_api, create_context=None)

    visible = resolve_visible_graphs([child, parent])

    assert [graph.target for graph in visible] == ["app.composition"]


def test_resolve_visible_graphs_keeps_partial_or_different_graphs() -> None:
    """Keep graphs when containment fails because bindings differ."""
    first = build_preview_graph(target="first.composition", api=bind_graph_api(), create_context=None)
    second_api = UseCaseAPI[None]()
    second_api.bind(CHILD, lambda caller: Handler(), uses=(LEAF,))
    second_api.bind(LEAF, lambda caller: Handler())
    second = build_preview_graph(target="second.composition", api=second_api, create_context=None)

    visible = resolve_visible_graphs([first, second])

    assert [graph.target for graph in visible] == [
        "first.composition",
        "second.composition",
    ]


def test_resolve_visible_graphs_keeps_one_representative_for_equivalent_graphs() -> None:
    """Keep one graph when equivalent graph snapshots compare as mutual containers."""
    given_api = bind_graph_api()
    first = build_preview_graph(target="composition", api=given_api, create_context=None)
    second = build_preview_graph(target="composition", api=given_api, create_context=None)

    visible = resolve_visible_graphs([second, first])

    assert len(visible) == 1
    assert visible[0].target == "composition"


def test_resolve_visible_graphs_keeps_graphs_when_edges_are_not_contained() -> None:
    """Keep graphs with the same nodes and bindings when edges are not a subset."""
    def parent_factory(caller: object) -> Handler:
        return Handler()

    def child_factory(caller: object) -> Handler:
        return Handler()

    def leaf_factory(caller: object) -> Handler:
        return Handler()

    first_api = UseCaseAPI[None]()
    first_api.bind(PARENT, parent_factory, uses=(CHILD,))
    first_api.bind(CHILD, child_factory)
    first_api.bind(LEAF, leaf_factory)
    second_api = UseCaseAPI[None]()
    second_api.bind(PARENT, parent_factory, uses=(LEAF,))
    second_api.bind(CHILD, child_factory)
    second_api.bind(LEAF, leaf_factory)
    first = build_preview_graph(target="first.composition", api=first_api, create_context=None)
    second = build_preview_graph(target="second.composition", api=second_api, create_context=None)

    visible = resolve_visible_graphs([second, first])

    assert [graph.target for graph in visible] == [
        "first.composition",
        "second.composition",
    ]


def test_resolve_visible_graphs_keeps_graphs_when_nodes_are_not_contained() -> None:
    """Keep graphs when neither node set contains the other."""
    def parent_factory(caller: object) -> Handler:
        return Handler()

    def child_factory(caller: object) -> Handler:
        return Handler()

    def leaf_factory(caller: object) -> Handler:
        return Handler()

    first_api = UseCaseAPI[None]()
    first_api.bind(PARENT, parent_factory, uses=(CHILD,))
    first_api.bind(CHILD, child_factory)
    second_api = UseCaseAPI[None]()
    second_api.bind(CHILD, child_factory, uses=(LEAF,))
    second_api.bind(LEAF, leaf_factory)
    first = build_preview_graph(target="first.composition", api=first_api, create_context=None)
    second = build_preview_graph(target="second.composition", api=second_api, create_context=None)

    visible = resolve_visible_graphs([second, first])

    assert [graph.target for graph in visible] == [
        "first.composition",
        "second.composition",
    ]


def test_route_groups_for_single_graph_use_plain_paths() -> None:
    """Generate unprefixed preview routes for a single visible graph."""
    graph = build_preview_graph(target="composition", api=bind_graph_api(), create_context=None)

    groups = route_groups_for_graphs([graph])

    assert [group.ref.key for group in groups] == [PARENT.key, CHILD.key, LEAF.key]
    assert groups[0].path == "/_usecases/commerce.checkout/v1/call"
    assert groups[0].operation_id == "commerce_checkout_v1_call"
    assert groups[0].tags == ("commerce.checkout@v1",)
    assert groups[1].tags == ("commerce.checkout@v1",)


def test_route_groups_for_multiple_graphs_use_composition_prefixes() -> None:
    """Prefix preview routes when multiple visible graphs are registered."""
    first = build_preview_graph(target="orders.composition", api=bind_graph_api(), create_context=None)
    second = build_preview_graph(target="payments.composition", api=bind_graph_api(), create_context=None)

    groups = route_groups_for_graphs([first, second])

    assert groups[0].path.startswith("/_compositions/orders.composition/_usecases/")
    assert groups[0].operation_id.startswith("orders_composition__")
    assert groups[0].tags == ("orders.composition / commerce.checkout@v1",)


def test_route_groups_assign_multiple_tags_to_shared_children() -> None:
    """Tag a shared child with every root flow that can reach it."""
    given_api = UseCaseAPI[None]()
    given_api.bind(PARENT, lambda caller: Handler(), uses=(LEAF,))
    given_api.bind(CHILD, lambda caller: Handler(), uses=(LEAF,))
    given_api.bind(LEAF, lambda caller: Handler())
    graph = build_preview_graph(target="composition", api=given_api, create_context=None)

    groups = route_groups_for_graphs([graph])

    assert groups[2].ref.key == LEAF.key
    assert groups[2].tags == (
        "commerce.checkout@v1",
        "commerce.place_order@v1",
    )


def test_route_groups_return_no_groups_for_empty_graphs() -> None:
    """Do not invent routes or tags for empty graphs."""
    graph = build_preview_graph(target="empty.composition", api=UseCaseAPI[None](), create_context=None)

    groups = route_groups_for_graphs([graph])

    assert groups == []
