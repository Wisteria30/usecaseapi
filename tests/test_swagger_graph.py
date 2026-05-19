"""Swagger preview graph tests."""

from __future__ import annotations

from typing import Protocol

from usecaseapi import Contract, Model, UseCaseAPI, define_usecase
from usecaseapi.swagger_graph import build_preview_graph


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
