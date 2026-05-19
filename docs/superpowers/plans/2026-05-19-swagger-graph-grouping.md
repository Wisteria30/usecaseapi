# Swagger Graph Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `usecaseapi swagger` load multiple discovered compositions at once, build dependency graphs from declared `uses`, collapse true subgraphs into their parent graph, and render remaining flows as collision-free Swagger groups.

**Architecture:** Split graph resolution out of `usecaseapi.swagger` into `usecaseapi.swagger_graph` so FastAPI routing stays separate from graph algorithms. Represent each composition as an immutable graph snapshot built from `UseCaseAPI.bindings`; use adjacency maps, memoized DFS, cycle detection, and set-based subgraph containment. Keep all preview state in memory and never create files inside the user's project.

**Tech Stack:** Python 3.12+, standard-library graph data structures (`dict`, `set`, `frozenset`, dataclasses), Typer CLI, optional FastAPI/Uvicorn, Pydantic v2.

---

## File Structure

- Create `src/usecaseapi/swagger_graph.py`
  - Owns graph snapshots, route grouping, cycle detection, subgraph containment, and deterministic tag assignment.
  - Does not import FastAPI or Uvicorn.
- Modify `src/usecaseapi/swagger.py`
  - Uses `swagger_graph.py` to load one or more preview compositions.
  - Registers FastAPI routes from graph route groups.
  - Keeps module/file import logic and context resolution.
- Modify `tests/test_swagger_preview.py`
  - Covers CLI-facing behavior and FastAPI route rendering for single and multiple compositions.
- Create `tests/test_swagger_graph.py`
  - Covers graph construction, cycle detection, reachability, subgraph containment, route path slugs, operation IDs, and tag assignment.
- Modify `docs/swagger-preview.md`
  - Documents multi-composition discovery, graph grouping, subgraph collapsing, and explicit `--preview` selection.

## Task 1: Add Graph Snapshot Types

**Files:**
- Create: `src/usecaseapi/swagger_graph.py`
- Test: `tests/test_swagger_graph.py`

- [ ] **Step 1: Write failing graph construction test**

Create `tests/test_swagger_graph.py` with these imports and helper contracts:

```python
"""Swagger preview graph tests."""

from __future__ import annotations

from typing import Protocol

import pytest

from usecaseapi import Contract, Model, UseCaseAPI, UseCaseRef, define_usecase
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
    api = UseCaseAPI[None]()
    api.bind(PARENT, lambda caller: Handler(), uses=(CHILD,))
    api.bind(CHILD, lambda caller: Handler(), uses=(LEAF,))
    api.bind(LEAF, lambda caller: Handler())
    return api


def test_build_preview_graph_uses_declared_dependencies() -> None:
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_swagger_graph.py::test_build_preview_graph_uses_declared_dependencies -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'usecaseapi.swagger_graph'`.

- [ ] **Step 3: Implement graph snapshot construction**

Create `src/usecaseapi/swagger_graph.py`:

```python
"""Graph resolution for development-only Swagger preview support."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .api import Binding, UseCaseAPI
from .errors import UseCaseAPIError


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
    binding_by_key = {binding.ref.key: binding for binding in api.bindings}
    nodes = frozenset(binding_by_key)
    edges = frozenset(
        (binding.ref.key, used_key)
        for binding in api.bindings
        for used_key in binding.uses
        if used_key in nodes
    )
    mutable_children = {key: set[str]() for key in nodes}
    mutable_parents = {key: set[str]() for key in nodes}
    for parent, child in edges:
        mutable_children[parent].add(child)
        mutable_parents[child].add(parent)
    children_by_parent = {
        key: frozenset(children) for key, children in mutable_children.items()
    }
    parents_by_child = {
        key: frozenset(parents) for key, parents in mutable_parents.items()
    }
    roots = frozenset(key for key, parents in parents_by_child.items() if not parents)
    return PreviewGraph(
        target=target,
        api=api,
        create_context=create_context,
        nodes=nodes,
        edges=edges,
        children_by_parent=children_by_parent,
        parents_by_child=parents_by_child,
        roots=roots,
        binding_by_key=binding_by_key,
    )
```

- [ ] **Step 4: Run graph construction test**

Run:

```bash
uv run pytest tests/test_swagger_graph.py::test_build_preview_graph_uses_declared_dependencies -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/usecaseapi/swagger_graph.py tests/test_swagger_graph.py
git commit -m "feat: build swagger preview dependency graphs"
```

## Task 2: Add Cycle Detection and Reachability

**Files:**
- Modify: `src/usecaseapi/swagger_graph.py`
- Test: `tests/test_swagger_graph.py`

- [ ] **Step 1: Write failing cycle and reachability tests**

Append to `tests/test_swagger_graph.py`:

```python
from usecaseapi.swagger_graph import SwaggerGraphError, reachable_nodes_by_root


def test_build_preview_graph_rejects_dependency_cycles() -> None:
    given_api = UseCaseAPI[None]()
    given_api.bind(PARENT, lambda caller: Handler(), uses=(CHILD,))
    given_api.bind(CHILD, lambda caller: Handler(), uses=(PARENT,))

    with pytest.raises(SwaggerGraphError, match="dependency cycle detected"):
        build_preview_graph(target="composition", api=given_api, create_context=None)


def test_reachable_nodes_by_root_memoizes_dependency_flows() -> None:
    graph = build_preview_graph(target="composition", api=bind_graph_api(), create_context=None)

    reachable = reachable_nodes_by_root(graph)

    assert reachable == {
        PARENT.key: frozenset({PARENT.key, CHILD.key, LEAF.key}),
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_swagger_graph.py -q
```

Expected: FAIL because `SwaggerGraphError` and `reachable_nodes_by_root` are not defined.

- [ ] **Step 3: Implement cycle detection and memoized reachability**

Update `src/usecaseapi/swagger_graph.py`:

```python
class SwaggerGraphError(UseCaseAPIError):
    """Raised when preview dependency graphs cannot be resolved."""


def detect_cycle(graph: PreviewGraph) -> tuple[str, ...] | None:
    """Return a cycle path if the graph contains one."""
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> tuple[str, ...] | None:
        if node in visiting:
            index = stack.index(node)
            return tuple((*stack[index:], node))
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
        "dependency cycle detected in "
        f"{graph.target}: " + " -> ".join(cycle)
    )


def reachable_nodes_by_root(graph: PreviewGraph) -> dict[str, frozenset[str]]:
    """Return every node reachable from each root usecase."""
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
```

Also update `build_preview_graph` before returning:

```python
    graph = PreviewGraph(
        target=target,
        api=api,
        create_context=create_context,
        nodes=nodes,
        edges=edges,
        children_by_parent=children_by_parent,
        parents_by_child=parents_by_child,
        roots=roots,
        binding_by_key=binding_by_key,
    )
    require_acyclic(graph)
    return graph
```

- [ ] **Step 4: Run graph tests**

Run:

```bash
uv run pytest tests/test_swagger_graph.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/usecaseapi/swagger_graph.py tests/test_swagger_graph.py
git commit -m "feat: resolve swagger preview graph roots"
```

## Task 3: Add Subgraph Containment Resolution

**Files:**
- Modify: `src/usecaseapi/swagger_graph.py`
- Test: `tests/test_swagger_graph.py`

- [ ] **Step 1: Write failing containment tests**

Append to `tests/test_swagger_graph.py`:

```python
from usecaseapi.swagger_graph import resolve_visible_graphs


def test_resolve_visible_graphs_collapses_true_subgraphs() -> None:
    parent_api = bind_graph_api()
    child_api = UseCaseAPI[None]()
    child_api.bind(CHILD, parent_api.binding_for_key(CHILD.key).factory, uses=(LEAF,))
    child_api.bind(LEAF, parent_api.binding_for_key(LEAF.key).factory)
    parent = build_preview_graph(target="app.composition", api=parent_api, create_context=None)
    child = build_preview_graph(target="commerce.composition", api=child_api, create_context=None)

    visible = resolve_visible_graphs([child, parent])

    assert [graph.target for graph in visible] == ["app.composition"]


def test_resolve_visible_graphs_keeps_partial_or_different_graphs() -> None:
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_swagger_graph.py -q
```

Expected: FAIL because `resolve_visible_graphs` is not defined.

- [ ] **Step 3: Implement containment with binding identity**

Update `src/usecaseapi/swagger_graph.py`:

```python
@dataclass(frozen=True, slots=True)
class BindingIdentity:
    """Process-local identity for a preview binding implementation."""

    factory_id: int
    factory_module: str
    factory_qualname: str


def binding_identity(factory: Callable[..., Any]) -> BindingIdentity:
    """Return a deterministic-enough process-local binding identity."""
    return BindingIdentity(
        factory_id=id(factory),
        factory_module=getattr(factory, "__module__", type(factory).__module__),
        factory_qualname=getattr(factory, "__qualname__", type(factory).__qualname__),
    )
```

Add `binding_identity_by_key` to `PreviewGraph`:

```python
    binding_identity_by_key: Mapping[str, BindingIdentity]
```

Set it in `build_preview_graph`:

```python
    binding_identity_by_key = {
        key: binding_identity(binding.factory)
        for key, binding in binding_by_key.items()
    }
```

Pass it into `PreviewGraph`.

Add containment functions:

```python
def graph_contains(parent: PreviewGraph, child: PreviewGraph) -> bool:
    """Return whether child is a true implementation-equivalent subgraph of parent."""
    if parent is child:
        return False
    if not child.nodes <= parent.nodes:
        return False
    if not child.edges <= parent.edges:
        return False
    if parent.create_context is not child.create_context:
        return False
    return all(
        parent.binding_identity_by_key[key] == child.binding_identity_by_key[key]
        for key in child.nodes
    )


def resolve_visible_graphs(graphs: list[PreviewGraph]) -> list[PreviewGraph]:
    """Remove graphs that are fully contained by another graph."""
    visible: list[PreviewGraph] = []
    for candidate in sorted(graphs, key=lambda graph: graph.target):
        contained = any(
            graph_contains(parent, candidate)
            for parent in graphs
            if parent is not candidate
        )
        if not contained:
            visible.append(candidate)
    return visible
```

- [ ] **Step 4: Run graph tests**

Run:

```bash
uv run pytest tests/test_swagger_graph.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/usecaseapi/swagger_graph.py tests/test_swagger_graph.py
git commit -m "feat: collapse contained swagger preview graphs"
```

## Task 4: Add Route Group Generation

**Files:**
- Modify: `src/usecaseapi/swagger_graph.py`
- Test: `tests/test_swagger_graph.py`

- [ ] **Step 1: Write failing route group tests**

Append to `tests/test_swagger_graph.py`:

```python
from usecaseapi.swagger_graph import route_groups_for_graphs


def test_route_groups_for_single_graph_use_plain_paths() -> None:
    graph = build_preview_graph(target="composition", api=bind_graph_api(), create_context=None)

    groups = route_groups_for_graphs([graph])

    assert [group.ref.key for group in groups] == [PARENT.key, CHILD.key, LEAF.key]
    assert groups[0].path == "/_usecases/commerce.checkout/v1/call"
    assert groups[0].operation_id == "commerce_checkout_v1_call"
    assert groups[0].tags == ("commerce.checkout@v1",)
    assert groups[1].tags == ("commerce.checkout@v1",)


def test_route_groups_for_multiple_graphs_use_composition_prefixes() -> None:
    first = build_preview_graph(target="orders.composition", api=bind_graph_api(), create_context=None)
    second = build_preview_graph(target="payments.composition", api=bind_graph_api(), create_context=None)

    groups = route_groups_for_graphs([first, second])

    assert groups[0].path.startswith("/_compositions/orders.composition/_usecases/")
    assert groups[0].operation_id.startswith("orders_composition__")
    assert groups[0].tags == ("orders.composition / commerce.checkout@v1",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_swagger_graph.py -q
```

Expected: FAIL because `route_groups_for_graphs` is not defined.

- [ ] **Step 3: Implement route group data and slug helpers**

Update `src/usecaseapi/swagger_graph.py`:

```python
import base64
import re

from .contracts import UseCaseRef


ROUTE_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True, slots=True)
class PreviewRouteGroup:
    """FastAPI route registration data for one preview binding."""

    graph: PreviewGraph
    ref: UseCaseRef[Any, Any]
    path: str
    operation_id: str
    tags: tuple[str, ...]


def route_segment(value: str) -> str:
    """Return a URL-safe route segment without losing the original identity."""
    if ROUTE_SAFE_SEGMENT.fullmatch(value):
        return value
    encoded = base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")
    return f"~{encoded}"


def operation_segment(value: str) -> str:
    """Return a stable OpenAPI operation id segment."""
    return re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_")
```

Add route generation:

```python
def route_groups_for_graphs(graphs: list[PreviewGraph]) -> list[PreviewRouteGroup]:
    """Return route registration groups for visible graphs."""
    multi_graph = len(graphs) > 1
    groups: list[PreviewRouteGroup] = []
    for graph in sorted(graphs, key=lambda item: item.target):
        tags_by_key = tags_by_usecase_key(graph, include_target=multi_graph)
        for binding in graph.api.bindings:
            ref = binding.ref
            path = preview_path_for_ref(graph=graph, ref=ref, include_target=multi_graph)
            operation_id = preview_operation_id_for_ref(
                graph=graph,
                ref=ref,
                include_target=multi_graph,
            )
            groups.append(
                PreviewRouteGroup(
                    graph=graph,
                    ref=ref,
                    path=path,
                    operation_id=operation_id,
                    tags=tags_by_key[ref.key],
                )
            )
    return groups


def tags_by_usecase_key(
    graph: PreviewGraph,
    *,
    include_target: bool,
) -> dict[str, tuple[str, ...]]:
    """Assign each usecase to every root flow that reaches it."""
    reachable = reachable_nodes_by_root(graph)
    tags: dict[str, list[str]] = {key: [] for key in graph.nodes}
    for root, reachable_nodes in sorted(reachable.items()):
        label = root
        if include_target:
            label = f"{graph.target} / {root}"
        for key in reachable_nodes:
            tags[key].append(label)
    return {key: tuple(values) for key, values in tags.items()}


def preview_path_for_ref(
    *,
    graph: PreviewGraph,
    ref: UseCaseRef[Any, Any],
    include_target: bool,
) -> str:
    """Return the FastAPI route path for one preview usecase."""
    usecase_path = f"/_usecases/{route_segment(ref.contract.name)}/v{ref.contract.version}/call"
    if not include_target:
        return usecase_path
    return f"/_compositions/{route_segment(graph.target)}{usecase_path}"


def preview_operation_id_for_ref(
    *,
    graph: PreviewGraph,
    ref: UseCaseRef[Any, Any],
    include_target: bool,
) -> str:
    """Return a collision-free OpenAPI operation id."""
    operation_id = operation_segment(ref.contract.name) + f"_v{ref.contract.version}_call"
    if not include_target:
        return operation_id
    return f"{operation_segment(graph.target)}__{operation_id}"
```

- [ ] **Step 4: Run graph tests**

Run:

```bash
uv run pytest tests/test_swagger_graph.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/usecaseapi/swagger_graph.py tests/test_swagger_graph.py
git commit -m "feat: create swagger preview route groups"
```

## Task 5: Wire Multi-Composition Graphs into Swagger Preview

**Files:**
- Modify: `src/usecaseapi/swagger.py`
- Modify: `tests/test_swagger_preview.py`

- [ ] **Step 1: Write failing preview behavior tests**

Append to `tests/test_swagger_preview.py`:

```python
def test_load_preview_auto_discovers_multiple_independent_compositions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_composition_module(tmp_path / "src" / "orders" / "composition.py")
    write_composition_module(tmp_path / "src" / "payments" / "composition.py")
    monkeypatch.chdir(tmp_path)

    config = load_preview(None)

    assert [graph.target for graph in config.graphs] == [
        "orders.composition",
        "payments.composition",
    ]


def test_create_swagger_app_registers_multiple_graph_routes() -> None:
    from usecaseapi.swagger_graph import build_preview_graph

    first = build_preview_graph(
        target="orders.composition",
        api=make_bound_api(),
        create_context=None,
    )
    second = build_preview_graph(
        target="payments.composition",
        api=make_bound_api(),
        create_context=None,
    )

    app = swagger_module.create_swagger_app(graphs=(first, second))
    schema = app.openapi()

    assert any(path.startswith("/_compositions/orders.composition/") for path in schema["paths"])
    assert any(path.startswith("/_compositions/payments.composition/") for path in schema["paths"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_swagger_preview.py -q
```

Expected: FAIL because `PreviewConfig.api` is still a single `UseCaseAPI` and `create_swagger_app` does not accept `graphs`.

- [ ] **Step 3: Change `PreviewConfig` to graph-based state**

In `src/usecaseapi/swagger.py`, import:

```python
from .swagger_graph import (
    PreviewGraph,
    build_preview_graph,
    resolve_visible_graphs,
    route_groups_for_graphs,
)
```

Change `PreviewConfig`:

```python
@dataclass(frozen=True, slots=True)
class PreviewConfig:
    """Loaded Swagger preview graph configuration."""

    graphs: tuple[PreviewGraph, ...]
```

Update `load_preview`:

```python
def load_preview(preview: str | None) -> PreviewConfig:
    """Load Swagger preview compositions and validate exported configuration."""
    if preview is not None:
        module, export_name = import_preview_target(preview)
        api = preview_api_from_module(module, export_name=export_name)
        if not isinstance(api, UseCaseAPI):
            raise_preview_export_error()
        create_context = preview_context_from_module(module)
        graph = build_preview_graph(
            target=preview,
            api=api,
            create_context=create_context,
        )
        return PreviewConfig(graphs=(graph,))

    explicit = discover_preview_module_or_none()
    if explicit is not None:
        module = import_preview_file(explicit)
        api = preview_api_from_module(module, export_name=None)
        if not isinstance(api, UseCaseAPI):
            raise_preview_export_error()
        create_context = preview_context_from_module(module)
        graph = build_preview_graph(
            target=str(explicit),
            api=api,
            create_context=create_context,
        )
        return PreviewConfig(graphs=(graph,))

    graphs = [
        load_composition_graph(candidate)
        for candidate in discover_composition_targets()
    ]
    if not graphs:
        raise_missing_preview_target_error()
    return PreviewConfig(graphs=tuple(resolve_visible_graphs(graphs)))
```

Add small helper functions in `swagger.py` to keep the body readable:

```python
def discover_preview_module_or_none(*, cwd: Path | None = None) -> Path | None:
    try:
        return discover_preview_module(cwd=cwd)
    except SwaggerPreviewError:
        return None


def preview_context_from_module(module: ModuleType) -> Callable[..., Any] | None:
    create_context = getattr(module, "create_context", None)
    if create_context is not None and not callable(create_context):
        raise SwaggerPreviewError("preview module export 'create_context' must be callable")
    return create_context


def load_composition_graph(candidate: PreviewTargetCandidate) -> PreviewGraph:
    module = import_preview_module_name(candidate.target)
    api = preview_api_from_module(module, export_name=None)
    if not isinstance(api, UseCaseAPI):
        raise_preview_export_error()
    return build_preview_graph(
        target=candidate.target,
        api=api,
        create_context=preview_context_from_module(module),
    )
```

Add explicit error helpers in `swagger.py`:

```python
def raise_preview_export_error() -> None:
    exports = "', '".join((*API_EXPORT_NAMES, *FACTORY_EXPORT_NAMES))
    raise SwaggerPreviewError(
        f"preview module must export one of '{exports}' as a UseCaseAPI instance "
        "or a zero-argument factory returning one"
    )


def raise_missing_preview_target_error() -> None:
    expected = ", ".join(str(candidate) for candidate in PREVIEW_MODULE_CANDIDATES)
    raise SwaggerPreviewError(
        "could not find preview target; expected one of: "
        f"{expected}; or an importable composition module under src/ or the project root"
    )
```

- [ ] **Step 4: Change app creation to route groups**

Update `create_swagger_app` signature:

```python
def create_swagger_app(*, graphs: tuple[PreviewGraph, ...]) -> Any:
```

Route registration loop:

```python
    for group in route_groups_for_graphs(list(graphs)):
        ref = group.ref
        app.post(
            group.path,
            name=ref.contract.name,
            operation_id=group.operation_id,
            response_model=ref.contract.output,
            tags=list(group.tags),
        )(
            make_usecase_endpoint(
                api=group.graph.api,
                ref=ref,
                create_context=group.graph.create_context,
            )
        )
```

Update `serve_swagger_preview`:

```python
    config = load_preview(preview)
    app = create_swagger_app(graphs=config.graphs)
```

- [ ] **Step 5: Run preview tests**

Run:

```bash
uv run pytest tests/test_swagger_preview.py tests/test_swagger_graph.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/usecaseapi/swagger.py src/usecaseapi/swagger_graph.py tests/test_swagger_preview.py tests/test_swagger_graph.py
git commit -m "feat: render multiple swagger preview graphs"
```

## Task 6: Update Documentation

**Files:**
- Modify: `docs/swagger-preview.md`

- [ ] **Step 1: Update discovery documentation**

Replace the Discovery section with:

```markdown
## Discovery

When `--preview` is not provided, the command first checks explicit preview
files in this order:

1. `tests/usecaseapi_preview.py`
2. `dev/usecaseapi_preview.py`
3. `src/composition.py`
4. `composition.py`
5. `usecaseapi_preview.py`
6. `preview.py`

If none exist, it scans importable `composition.py` modules under `src/` and
the project root. Every discovered composition is loaded in memory. The command
builds a dependency graph from declared `uses`, collapses implementation-equivalent
subgraphs into their parent graph, and renders the remaining graphs in Swagger UI.

No files are generated in the application repository. The preview FastAPI app
exists only for the running command process.

You can point the command at one specific preview module or export:

```bash
uv run usecaseapi swagger --preview usecaseapi_preview
uv run usecaseapi swagger --preview app.composition:usecases
uv run usecaseapi swagger --preview app.composition:create_usecases
uv run usecaseapi swagger --preview tests/usecaseapi_preview.py
uv run usecaseapi swagger --preview path/to/usecaseapi_preview.py
```
```

- [ ] **Step 2: Add multi-composition behavior section**

Append after Discovery:

```markdown
## Multiple Compositions

When multiple compositions remain visible after graph resolution, preview routes
include the composition target to avoid OpenAPI path and operationId collisions:

```text
/_compositions/orders.composition/_usecases/orders.create_order/v1/call
/_compositions/payments.composition/_usecases/payments.authorize/v1/call
```

Swagger tags are assigned from dependency roots. If one root reaches a child
usecase through declared `uses`, the child operation receives the root tag too.
If a child is shared by two roots, the operation receives both tags.

Single-composition preview keeps the shorter route shape:

```text
/_usecases/orders.create_order/v1/call
```
```

- [ ] **Step 3: Run documentation-adjacent checks**

Run:

```bash
uv run ruff check docs
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add docs/swagger-preview.md
git commit -m "docs: explain swagger graph grouping"
```

## Task 7: Full Verification and Real Project Check

**Files:**
- No planned file edits.

- [ ] **Step 1: Run quality checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

Expected:

```text
All checks passed!
42 files already formatted
Success: no issues found in 43 source files
```

- [ ] **Step 2: Run coverage**

Run:

```bash
uv run coverage run -m pytest
uv run coverage report -m
```

Expected:

```text
170 passed
TOTAL ... 100%
```

The exact test count may increase after adding `tests/test_swagger_graph.py`; the coverage total must remain `100%`.

- [ ] **Step 3: Build and verify package**

Run:

```bash
uv build
uv run twine check dist/*
uv run --isolated --no-project --with dist/usecaseapi-2.1.2-py3-none-any.whl scripts/verify_distribution.py
uv run --isolated --no-project --with dist/usecaseapi-2.1.2.tar.gz scripts/verify_distribution.py
```

Expected: all commands exit with status 0.

- [ ] **Step 4: Verify against the janken project**

Run:

```bash
cd /Users/wis30/ghq/github.com/Wisteria30/janken
uv run --with-editable /Users/wis30/ghq/github.com/Wisteria30/usecaseapi usecaseapi swagger --port 8765
```

In another terminal, run:

```bash
curl -fsS -o /tmp/usecaseapi-janken-docs.html -w "%{http_code}" http://127.0.0.1:8765/docs
curl -fsS http://127.0.0.1:8765/openapi.json | uv run python -c 'import json, sys; data=json.load(sys.stdin); print(len(data["paths"])); print("\n".join(sorted(data["paths"])))'
```

Expected:

```text
200
```

The OpenAPI path list must include the janken and acchi-muite-hoi usecases.
If multiple visible compositions remain, paths must use `/_compositions/...`.
If graph containment collapses package compositions into an application graph,
paths may use the single-composition `/_usecases/...` shape.

- [ ] **Step 5: Commit any verification-only doc corrections**

If verification exposes a documentation mismatch, fix only the relevant docs and run:

```bash
uv run ruff check docs
git add docs/swagger-preview.md
git commit -m "docs: align swagger graph preview docs"
```

If no documentation mismatch is found, do not create a commit.

## Self-Review

- Spec coverage: The plan covers internal-only implementation, multiple composition loading, declared-`uses` graph construction, cycle detection, parent graph containment, separate tags for unrelated or partial graphs, collision-free paths and operation IDs, tests, docs, package verification, and the janken real-project check.
- Placeholder scan: No placeholders remain. Every code-changing step names the exact file, expected command, and expected result.
- Type consistency: `PreviewGraph`, `PreviewRouteGroup`, `build_preview_graph`, `resolve_visible_graphs`, and `route_groups_for_graphs` are introduced before they are used by `swagger.py`.
