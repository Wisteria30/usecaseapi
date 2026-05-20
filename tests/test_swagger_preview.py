"""Swagger preview module discovery tests."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys

from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, Protocol

import pytest

import usecaseapi._swagger.app as swagger_app_module
import usecaseapi._swagger.discovery as swagger_discovery_module
import usecaseapi.swagger as swagger_module

from usecaseapi import (
    Contract,
    Model,
    UseCase,
    UseCaseAPI,
    UseCaseError,
    UseCaseRef,
    define_usecase,
)
from usecaseapi.swagger import (
    SwaggerPreviewError,
    discover_preview_module,
    discover_preview_target,
    load_preview,
)
from usecaseapi.swagger_graph import PreviewGraph, build_preview_graph


class PreviewInput(Model):
    value: int


class PreviewOutput(Model):
    value: int


class MultiplierContext(Model):
    multiplier: int


class PreviewUseCase(UseCase[PreviewInput, PreviewOutput], Protocol):
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput: ...


PREVIEW_USECASE: UseCaseRef[PreviewInput, PreviewOutput] = define_usecase(
    PreviewUseCase,
    Contract(name="preview.run", version=1, input=PreviewInput, output=PreviewOutput),
)


class PreviewImpl:
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        return PreviewOutput(value=input.value + 1)


class PreviewRejected(UseCaseError):
    code: ClassVar[str] = "preview.rejected"

    def __init__(self, *, reason: str) -> None:
        """Create a rejected preview domain error."""
        self.reason = reason
        super().__init__(reason)


class RejectingImpl:
    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        raise PreviewRejected(reason="not allowed")


class ContextImpl:
    def __init__(self, multiplier: int) -> None:
        """Create a preview implementation that multiplies input values."""
        self.multiplier = multiplier

    async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
        return PreviewOutput(value=input.value * self.multiplier)


def make_bound_api() -> UseCaseAPI[None]:
    """Create a preview API with one bound usecase."""
    api = UseCaseAPI[None]()
    api.bind(PREVIEW_USECASE, lambda caller: PreviewImpl())
    return api


def make_preview_graph(api: UseCaseAPI[Any] | None = None) -> PreviewGraph:
    """Create a single preview graph for Swagger app tests."""
    return build_preview_graph(target="preview", api=api or make_bound_api(), create_context=None)


async def run_context_resolver(
    resolver: Callable[[object], Awaitable[Any]],
    request: object,
) -> Any:
    """Run a context resolver through a concrete coroutine for type checkers."""
    return await resolver(request)


def test_discovers_usecaseapi_preview_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default preview module is discovered from the current working directory."""
    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")
    monkeypatch.chdir(tmp_path)

    assert discover_preview_module() == preview_path


def test_discovers_dev_preview_before_root_preview(tmp_path: Path) -> None:
    """Project-local test preview modules take precedence over root preview files."""
    root_preview = tmp_path / "usecaseapi_preview.py"
    tests_preview = tmp_path / "tests" / "usecaseapi_preview.py"
    tests_preview.parent.mkdir()
    root_preview.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")
    tests_preview.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")

    assert discover_preview_module(cwd=tmp_path) == tests_preview


def test_discover_preview_module_reports_supported_names(tmp_path: Path) -> None:
    """Missing preview modules report the supported discovery filenames."""
    with pytest.raises(SwaggerPreviewError) as exc_info:
        discover_preview_module(cwd=tmp_path)

    message = str(exc_info.value)
    assert "could not find preview module" in message
    assert "tests/usecaseapi_preview.py" in message
    assert "usecaseapi_preview.py" in message
    assert "src/composition.py" in message


def write_composition_module(path: Path, *, export: str = "usecases") -> None:
    """Write a minimal importable UseCaseAPI composition module."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"from usecaseapi import UseCaseAPI\n\n{export} = UseCaseAPI[None]()\n",
        encoding="utf-8",
    )


def test_discovers_src_app_shell_composition_target(tmp_path: Path) -> None:
    """The default preview target can be an ordinary src app composition module."""
    write_composition_module(tmp_path / "src" / "app_shell" / "composition.py")

    assert discover_preview_target(cwd=tmp_path) == "app_shell.composition"


def test_discovers_app_composition_before_package_compositions(tmp_path: Path) -> None:
    """Whole-app composition modules are preferred over package-level compositions."""
    write_composition_module(tmp_path / "src" / "packages" / "janken" / "composition.py")
    write_composition_module(tmp_path / "src" / "packages" / "acchi" / "composition.py")
    write_composition_module(tmp_path / "src" / "app_shell" / "composition.py")

    assert discover_preview_target(cwd=tmp_path) == "app_shell.composition"


def test_discover_preview_target_reports_ambiguous_compositions(tmp_path: Path) -> None:
    """Equally likely app compositions fail explicitly instead of choosing arbitrarily."""
    write_composition_module(tmp_path / "src" / "orders" / "composition.py")
    write_composition_module(tmp_path / "src" / "payments" / "composition.py")

    with pytest.raises(SwaggerPreviewError, match="multiple equally likely preview targets"):
        discover_preview_target(cwd=tmp_path)


def test_discover_preview_target_reports_missing_candidates(tmp_path: Path) -> None:
    """A project without preview files or composition modules gets an actionable error."""
    with pytest.raises(SwaggerPreviewError, match="could not find preview target") as exc_info:
        discover_preview_target(cwd=tmp_path)

    assert "composition module under src/" in str(exc_info.value)


def test_discover_composition_targets_ignores_non_usecaseapi_files(tmp_path: Path) -> None:
    """Auto discovery scans composition.py files but keeps only UseCaseAPI-looking modules."""
    skipped = tmp_path / "src" / "skipped" / "composition.py"
    skipped.parent.mkdir(parents=True)
    skipped.write_text("value = 1\n", encoding="utf-8")
    invalid = tmp_path / "src" / "bad-name" / "composition.py"
    write_composition_module(invalid)
    accepted = tmp_path / "src" / "app_shell" / "composition.py"
    write_composition_module(accepted)

    targets = swagger_module.discover_composition_targets(cwd=tmp_path)

    assert [target.target for target in targets] == ["app_shell.composition"]


def test_discover_composition_targets_skips_rejected_auto_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto discovery rechecks rejected paths before converting them to import targets."""
    skipped = tmp_path / "src" / "composition.py"
    skipped.parent.mkdir()
    skipped.write_text("from usecaseapi import UseCaseAPI\nusecases = UseCaseAPI[None]()\n")

    monkeypatch.setattr(
        swagger_discovery_module,
        "project_import_roots",
        lambda root: (root,),
    )
    monkeypatch.setattr(
        swagger_discovery_module,
        "iter_composition_files",
        lambda import_root: [skipped],
    )

    assert swagger_discovery_module.discover_composition_targets(cwd=tmp_path) == []


def test_iter_composition_files_prunes_excluded_dirs(tmp_path: Path) -> None:
    """Auto discovery does not descend into cache or build output directories."""
    excluded = tmp_path / ".venv" / "composition.py"
    accepted = tmp_path / "app_shell" / "composition.py"
    excluded.parent.mkdir()
    accepted.parent.mkdir()
    excluded.write_text("ignored\n", encoding="utf-8")
    accepted.write_text("accepted\n", encoding="utf-8")

    assert swagger_discovery_module.iter_composition_files(tmp_path) == [accepted]


def test_iter_composition_files_ignores_unreadable_directories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unreadable directories are skipped during best-effort auto discovery."""

    def raise_oserror(_: Path) -> list[Path]:
        raise OSError("blocked")

    monkeypatch.setattr(Path, "iterdir", raise_oserror)

    assert swagger_discovery_module.iter_composition_files(tmp_path) == []


@pytest.mark.parametrize(
    ("path_parts", "import_root_parts", "under_import_root", "expected"),
    [
        (("composition.py",), ("src",), False, True),
        (("src", "app_shell", "composition.py"), (), True, True),
        (("app_shell", "composition.py"), ("src",), True, False),
    ],
)
def test_should_skip_auto_discovery_path_table(
    tmp_path: Path,
    path_parts: tuple[str, ...],
    import_root_parts: tuple[str, ...],
    under_import_root: bool,
    expected: bool,
) -> None:
    """Auto discovery skips paths outside ordinary importable source roots."""
    import_root = tmp_path.joinpath(*import_root_parts)
    candidate_base = import_root if under_import_root else tmp_path
    candidate = candidate_base.joinpath(*path_parts)

    result = swagger_module.should_skip_auto_discovery_path(candidate, import_root)

    assert result is expected


@pytest.mark.parametrize(
    ("path_parts", "expected"),
    [
        (("src", "app_shell", "composition.py"), "app_shell.composition"),
        (("src", "bad-name.py"), None),
        (("../composition.py",), None),
    ],
)
def test_module_name_from_path_table(
    tmp_path: Path,
    path_parts: tuple[str, ...],
    expected: str | None,
) -> None:
    """Import module names are derived only from valid Python path segments."""
    import_root = tmp_path / "src"
    candidate = tmp_path.joinpath(*path_parts)

    result = swagger_module.module_name_from_path(candidate, import_root)

    assert result == expected


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("def broken(:\n", False),
        ("from usecaseapi import UseCaseAPI\nusecases: UseCaseAPI[None]\n", True),
        (
            "from usecaseapi import UseCaseAPI\n"
            "async def create_usecases():\n"
            "    return UseCaseAPI[None]()\n",
            True,
        ),
    ],
)
def test_looks_like_usecaseapi_composition_table(
    tmp_path: Path,
    content: str,
    expected: bool,
) -> None:
    """Composition detection is syntax-tolerant and based on public export names."""
    candidate = tmp_path / "src" / "app_shell" / "composition.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(content, encoding="utf-8")

    result = swagger_module.looks_like_usecaseapi_composition(candidate)

    assert result is expected


@pytest.mark.parametrize(
    ("module_name", "expected"),
    [
        ("app_shell.composition", (0, 2)),
        ("composition", (1, 1)),
        ("shop.composition", (2, 2)),
        ("packages.janken.composition", (3, 3)),
    ],
)
def test_preview_target_score_table(module_name: str, expected: tuple[int, int]) -> None:
    """Preview target ranking prefers application compositions over package internals."""
    result = swagger_module.preview_target_score(module_name)

    assert result == expected


def test_load_preview_auto_discovers_src_composition_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default preview loader imports the discovered src composition module."""
    write_composition_module(tmp_path / "src" / "app_shell" / "composition.py")
    monkeypatch.chdir(tmp_path)

    config = load_preview(None)

    assert len(config.graphs) == 1
    assert isinstance(config.graphs[0].api, UseCaseAPI)
    assert config.graphs[0].target == "app_shell.composition"


def test_load_preview_auto_discovers_multiple_independent_compositions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default preview loader imports every discovered independent composition."""
    orders = tmp_path / "src" / "orders" / "composition.py"
    payments = tmp_path / "src" / "payments" / "composition.py"
    orders.parent.mkdir(parents=True)
    payments.parent.mkdir(parents=True)
    module_source = """
from typing import Protocol

from usecaseapi import Contract, Model, UseCaseAPI, define_usecase


class Input(Model):
    value: int


class Output(Model):
    value: int


class RunUseCase(Protocol):
    async def __call__(self, input: Input) -> Output: ...


class Handler:
    async def __call__(self, input: Input) -> Output:
        return Output(value=input.value)


RUN = define_usecase(
    RunUseCase,
    Contract(name="{contract_name}", version=1, input=Input, output=Output),
)
usecases = UseCaseAPI[None]()
usecases.bind(RUN, lambda caller: Handler())
"""
    orders.write_text(
        module_source.format(contract_name="orders.run").lstrip(),
        encoding="utf-8",
    )
    payments.write_text(
        module_source.format(contract_name="payments.run").lstrip(),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = load_preview(None)

    assert [graph.target for graph in config.graphs] == [
        "orders.composition",
        "payments.composition",
    ]


def test_load_preview_accepts_module_export_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit module:export targets load without a preview-only file."""
    write_composition_module(tmp_path / "src" / "app_shell" / "composition.py")
    monkeypatch.chdir(tmp_path)

    config = load_preview("app_shell.composition:usecases")

    assert len(config.graphs) == 1
    assert isinstance(config.graphs[0].api, UseCaseAPI)
    assert config.graphs[0].target == "app_shell.composition:usecases"


def test_load_preview_rejects_explicit_target_without_api_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit preview targets must expose a UseCaseAPI instance or factory."""
    preview_path = tmp_path / "src" / "lazy_app" / "composition.py"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_text("value = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SwaggerPreviewError, match="UseCaseAPI instance"):
        load_preview("app_shell.composition:value")


def test_load_preview_reports_missing_preview_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The graph loader keeps the missing-target error actionable."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SwaggerPreviewError, match="could not find preview target") as exc_info:
        load_preview(None)

    assert "tests/usecaseapi_preview.py" in str(exc_info.value)
    assert "composition module under src/" in str(exc_info.value)


def test_load_preview_accepts_zero_argument_usecase_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Composition modules can expose a zero-argument create_usecases factory."""
    preview_path = tmp_path / "src" / "required_factory" / "composition.py"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_text(
        "from usecaseapi import UseCaseAPI\n\n"
        "def create_usecases() -> UseCaseAPI[None]:\n"
        "    return UseCaseAPI[None]()\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = load_preview(None)

    assert len(config.graphs) == 1
    assert isinstance(config.graphs[0].api, UseCaseAPI)


def test_load_preview_keeps_project_import_roots_during_factory_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview factories can lazily import project modules under src."""
    builder_path = tmp_path / "src" / "builders.py"
    preview_path = tmp_path / "src" / "lazy_app" / "composition.py"
    builder_path.parent.mkdir(parents=True)
    preview_path.parent.mkdir(parents=True)
    builder_path.write_text(
        "from usecaseapi import UseCaseAPI\n\n"
        "def make_api() -> UseCaseAPI[None]:\n"
        "    return UseCaseAPI[None]()\n",
        encoding="utf-8",
    )
    preview_path.write_text(
        "from usecaseapi import UseCaseAPI\n\n"
        "def create_usecases() -> UseCaseAPI[None]:\n"
        "    from builders import make_api\n"
        "    return make_api()\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = load_preview("lazy_app.composition:create_usecases")

    assert len(config.graphs) == 1
    assert isinstance(config.graphs[0].api, UseCaseAPI)


def test_load_preview_rejects_factory_with_required_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto factories must be callable without user-provided arguments."""
    preview_path = tmp_path / "src" / "wrong_factory" / "composition.py"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_text(
        "from usecaseapi import UseCaseAPI\n\n"
        "def create_usecases(required: str) -> UseCaseAPI[None]:\n"
        "    return UseCaseAPI[None]()\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SwaggerPreviewError, match="zero-argument factory"):
        load_preview(None)


def test_load_preview_ignores_factory_returning_wrong_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factories must return a UseCaseAPI instance."""
    preview_path = tmp_path / "src" / "wrong_return_factory" / "composition.py"
    preview_path.parent.mkdir(parents=True)
    preview_path.write_text("def create_usecases():\n    return object()\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SwaggerPreviewError, match="UseCaseAPI instance"):
        load_preview(None)


def test_import_preview_module_returns_auto_discovered_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The import helper returns the module half of the discovered preview target."""
    write_composition_module(tmp_path / "src" / "app_shell" / "composition.py")
    monkeypatch.chdir(tmp_path)

    module = swagger_module.import_preview_module(None)

    assert module.__name__ == "app_shell.composition"


def test_split_preview_export_rejects_invalid_target() -> None:
    """Invalid module:export syntax fails before import."""
    with pytest.raises(SwaggerPreviewError, match="invalid preview target"):
        swagger_module.split_preview_export("app_shell.composition:")


def test_callable_signature_errors_are_not_zero_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callables whose signature cannot be inspected are not invoked automatically."""

    def factory() -> UseCaseAPI[None]:
        return UseCaseAPI[None]()

    def raise_type_error(_: object) -> object:
        raise TypeError("no signature")

    monkeypatch.setattr(inspect, "signature", raise_type_error)

    assert swagger_module.callable_accepts_no_required_arguments(factory) is False


def test_async_factory_is_not_zero_argument_preview_factory() -> None:
    """Preview factories are synchronous so auto loading never creates a coroutine."""

    async def factory() -> UseCaseAPI[None]:
        return UseCaseAPI[None]()

    assert swagger_module.callable_accepts_no_required_arguments(factory) is False


def test_load_preview_requires_api_export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preview modules must export a supported UseCaseAPI instance."""
    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("value = 1\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SwaggerPreviewError, match="preview module must export one of"):
        load_preview(None)


def test_load_preview_accepts_usecases_export(tmp_path: Path) -> None:
    """Existing composition modules can expose usecases without a preview-only api alias."""
    preview_path = tmp_path / "composition.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\n\nusecases = UseCaseAPI[None]()\n")

    config = load_preview(str(preview_path))

    assert len(config.graphs) == 1
    assert isinstance(config.graphs[0].api, UseCaseAPI)


def test_load_preview_requires_callable_context_factory(tmp_path: Path) -> None:
    """Preview modules must not export non-callable create_context values."""
    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text(
        "from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\ncreate_context = 1\n"
    )

    with pytest.raises(SwaggerPreviewError, match="create_context"):
        load_preview(str(preview_path))


def test_create_swagger_app_calls_bound_usecase() -> None:
    """The preview app exposes a bound usecase as a POST endpoint."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    client = TestClient(create_swagger_app(graphs=(make_preview_graph(),)))

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 4})

    assert response.status_code == 200
    assert response.json() == {"value": 5}


def test_domain_errors_are_returned_as_envelopes() -> None:
    """Domain errors are serialized as explicit JSON envelopes."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    ref: UseCaseRef[PreviewInput, PreviewOutput] = define_usecase(
        PreviewUseCase,
        Contract(
            name="preview.reject",
            version=1,
            input=PreviewInput,
            output=PreviewOutput,
            raises=(PreviewRejected,),
            known_errors=(PreviewRejected,),
        ),
    )
    api = UseCaseAPI[None]()
    api.bind(ref, lambda caller: RejectingImpl())
    client = TestClient(create_swagger_app(graphs=(make_preview_graph(api),)))

    response = client.post("/_usecases/preview.reject/v1/call", json={"value": 1})

    assert response.status_code == 400
    assert response.json() == {
        "code": "preview.rejected",
        "error": "PreviewRejected",
        "message": "not allowed",
        "payload": {"reason": "not allowed"},
    }


def test_swagger_docs_include_usecase_path() -> None:
    """FastAPI OpenAPI output includes the canonical UseCaseAPI route path."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    client = TestClient(create_swagger_app(graphs=(make_preview_graph(),)))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/_usecases/preview.run/v1/call" in response.json()["paths"]


def test_create_swagger_app_registers_multiple_graph_routes() -> None:
    """Multiple preview graphs are registered under composition route prefixes."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

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
    client = TestClient(create_swagger_app(graphs=(first, second)))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/_compositions/orders.composition/_usecases/preview.run/v1/call" in paths
    assert "/_compositions/payments.composition/_usecases/preview.run/v1/call" in paths


def test_swagger_route_path_encodes_reserved_contract_name_syntax() -> None:
    """Contract names containing path syntax still produce callable preview routes."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import (
        create_swagger_app,
        preview_operation_id,
        preview_route_name,
        preview_route_path,
    )

    ref: UseCaseRef[PreviewInput, PreviewOutput] = define_usecase(
        PreviewUseCase,
        Contract(name="preview/{tenant}/run", version=1, input=PreviewInput, output=PreviewOutput),
    )
    api = UseCaseAPI[None]()
    api.bind(ref, lambda caller: PreviewImpl())
    client = TestClient(create_swagger_app(graphs=(make_preview_graph(api),)))
    route_name = preview_route_name(ref.contract.name)
    route_path = f"/_usecases/{route_name}/v1/call"

    response = client.post(route_path, json={"value": 4})

    assert route_name == "~cHJldmlldy97dGVuYW50fS9ydW4"
    assert preview_route_path(ref) == route_path
    assert preview_operation_id(ref).endswith("_v1_call")
    assert response.status_code == 200
    assert response.json() == {"value": 5}
    assert route_path in client.get("/openapi.json").json()["paths"]


def test_swagger_docs_include_preview_scenario_header_parameter() -> None:
    """FastAPI OpenAPI output exposes the preview scenario header."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    client = TestClient(create_swagger_app(graphs=(make_preview_graph(),)))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    operation = response.json()["paths"]["/_usecases/preview.run/v1/call"]["post"]
    scenario_parameter = next(
        parameter
        for parameter in operation["parameters"]
        if parameter["name"] == "x-usecaseapi-scenario" and parameter["in"] == "header"
    )
    scenario_schema = scenario_parameter["schema"]
    request_body_schema = operation["requestBody"]["content"]["application/json"]["schema"]

    assert scenario_parameter["required"] is False
    assert scenario_schema.get("type") == "string" or {"type": "string"} in scenario_schema.get(
        "anyOf", []
    )
    assert request_body_schema == {"$ref": "#/components/schemas/PreviewInput"}


def test_create_swagger_app_supports_keyword_only_request_context() -> None:
    """Keyword-only request factories can create the per-request context."""
    from fastapi import Request
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    class ContextPreviewImpl:
        def __init__(self, increment: int) -> None:
            self.increment = increment

        async def __call__(self, input: PreviewInput, /) -> PreviewOutput:
            return PreviewOutput(value=input.value + self.increment)

    def create_context(*, request: Request) -> int:
        assert request.url.path == "/_usecases/preview.run/v1/call"
        return 6

    api = UseCaseAPI[int]()
    api.bind(PREVIEW_USECASE, lambda caller: ContextPreviewImpl(caller.context))
    graph = build_preview_graph(target="preview", api=api, create_context=create_context)
    client = TestClient(create_swagger_app(graphs=(graph,)))

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 4})

    assert response.status_code == 200
    assert response.json() == {"value": 10}


def test_create_swagger_app_supports_zero_argument_context_factory() -> None:
    """Zero-argument context factories are evaluated once per request."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    api = UseCaseAPI[MultiplierContext]()
    api.bind(PREVIEW_USECASE, lambda caller: ContextImpl(caller.context.multiplier))

    def create_context() -> MultiplierContext:
        return MultiplierContext(multiplier=5)

    graph = build_preview_graph(target="preview", api=api, create_context=create_context)
    client = TestClient(create_swagger_app(graphs=(graph,)))

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 3})

    assert response.status_code == 200
    assert response.json() == {"value": 15}


def test_request_headers_can_drive_preview_context() -> None:
    """Preview context factories can read the current HTTP request."""
    from fastapi import Request
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    api = UseCaseAPI[MultiplierContext]()
    api.bind(PREVIEW_USECASE, lambda caller: ContextImpl(caller.context.multiplier))

    async def create_context(request: Request) -> MultiplierContext:
        return MultiplierContext(multiplier=int(request.headers["x-multiplier"]))

    graph = build_preview_graph(target="preview", api=api, create_context=create_context)
    client = TestClient(create_swagger_app(graphs=(graph,)))

    response = client.post(
        "/_usecases/preview.run/v1/call",
        json={"value": 3},
        headers={"x-multiplier": "4"},
    )

    assert response.status_code == 200
    assert response.json() == {"value": 12}


def test_context_argument_mode_table() -> None:
    """Context factory signatures are classified once when endpoints are built."""

    def no_arguments() -> None:
        return None

    def positional_request(request: object) -> object:
        return request

    def keyword_request(*, request: object) -> object:
        return request

    def unsupported(first: object, second: object) -> None:
        raise AssertionError("unsupported factory should not be called")

    assert swagger_app_module.context_argument_mode(no_arguments) == "none"
    assert swagger_app_module.context_argument_mode(positional_request) == "positional_request"
    assert swagger_app_module.context_argument_mode(keyword_request) == "keyword_request"
    with pytest.raises(SwaggerPreviewError, match="zero arguments or one request argument"):
        swagger_app_module.context_argument_mode(unsupported)


def test_context_resolver_modes_return_sync_and_async_values() -> None:
    """Context resolvers support the explicit zero, positional, and keyword request modes."""

    async def async_context() -> str:
        return "async-context"

    def no_arguments() -> object:
        return async_context()

    def positional_request(request: object) -> object:
        return request

    def keyword_request(*, request: object) -> tuple[str, object]:
        return ("keyword", request)

    assert (
        asyncio.run(
            run_context_resolver(
                swagger_app_module.context_resolver_for_mode(no_arguments, "none"),
                object(),
            )
        )
        == "async-context"
    )
    request = object()
    assert (
        asyncio.run(
            run_context_resolver(
                swagger_app_module.context_resolver_for_mode(
                    positional_request,
                    "positional_request",
                ),
                request,
            )
        )
        is request
    )
    assert asyncio.run(
        run_context_resolver(
            swagger_app_module.context_resolver_for_mode(
                keyword_request,
                "keyword_request",
            ),
            request,
        )
    ) == ("keyword", request)


def test_build_context_resolver_defers_invalid_signature_errors() -> None:
    """Invalid preview context signatures are raised when the preview route is invoked."""

    def unsupported(first: object, second: object) -> None:
        raise AssertionError("unsupported factory should not be called")

    resolver = swagger_app_module.build_context_resolver(unsupported)

    with pytest.raises(SwaggerPreviewError, match="zero arguments or one request argument"):
        asyncio.run(run_context_resolver(resolver, object()))


def test_resolve_context_supports_missing_factory() -> None:
    """The public resolver helper keeps the default preview context as None."""
    assert asyncio.run(swagger_app_module.resolve_context(None, object())) is None


def test_basic_example_preview_module_runs_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    """The basic example preview module exposes inventory scenarios."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    monkeypatch.chdir("examples/basic")

    config = load_preview(None)
    client = TestClient(create_swagger_app(graphs=config.graphs))
    payload = {"user_id": "user_123", "item": {"sku_id": "sku_456", "quantity": 2}}

    accepted = client.post("/_usecases/commerce.place_order/v1/call", json=payload)
    shortage = client.post(
        "/_usecases/commerce.place_order/v1/call",
        json=payload,
        headers={"x-usecaseapi-scenario": "empty"},
    )

    assert accepted.status_code == 200
    assert accepted.json() == {"order_id": "ord_123", "status": "accepted"}
    assert shortage.status_code == 400
    assert shortage.json()["code"] == "commerce.place_order.inventory_shortage"


def test_basic_example_preview_module_rejects_unknown_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The basic preview reports unknown inventory scenarios explicitly."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    monkeypatch.chdir("examples/basic")

    config = load_preview(None)
    client = TestClient(
        create_swagger_app(graphs=config.graphs),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/_usecases/commerce.place_order/v1/call",
        json={"user_id": "user_123", "item": {"sku_id": "sku_456", "quantity": 2}},
        headers={"x-usecaseapi-scenario": "unknown"},
    )

    assert response.status_code == 500
    assert "unknown x-usecaseapi-scenario value 'unknown'" in response.text
    assert "default" in response.text
    assert "empty" in response.text
    assert "rich" in response.text


def test_context_factory_rejects_unsupported_signature() -> None:
    """Preview context factories must have a supported signature."""
    from fastapi.testclient import TestClient

    from usecaseapi.swagger import create_swagger_app

    def create_context(first: object, second: object) -> None:
        raise AssertionError("unsupported context factory should not be called")

    client = TestClient(
        create_swagger_app(
            graphs=(
                build_preview_graph(
                    target="preview",
                    api=make_bound_api(),
                    create_context=create_context,
                ),
            )
        ),
        raise_server_exceptions=False,
    )

    response = client.post("/_usecases/preview.run/v1/call", json={"value": 1})

    assert response.status_code == 500
    assert "create_context must accept zero arguments or one request argument" in response.text


def test_create_swagger_app_reports_missing_fastapi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing preview dependencies produce an explicit install error."""
    import builtins

    from usecaseapi.swagger import create_swagger_app

    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_: Mapping[str, object] | None = None,
        locals_: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "fastapi":
            raise ImportError("blocked fastapi")
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(SwaggerPreviewError, match="uv sync --extra swagger"):
        create_swagger_app(graphs=(make_preview_graph(),))


def test_serve_swagger_preview_reports_missing_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing server dependencies produce an explicit install error."""
    import builtins

    from usecaseapi.swagger import serve_swagger_preview

    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals_: Mapping[str, object] | None = None,
        locals_: Mapping[str, object] | None = None,
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "uvicorn":
            raise ImportError("blocked uvicorn")
        return original_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(SwaggerPreviewError, match="uv sync --extra swagger"):
        serve_swagger_preview(preview=None, host="127.0.0.1", port=8000)


def test_serve_swagger_preview_loads_app_and_starts_uvicorn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The server wrapper loads preview config and delegates to uvicorn."""
    from usecaseapi.swagger import serve_swagger_preview

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")
    calls: list[dict[str, object]] = []

    def run(app: object, *, host: str, port: int) -> None:
        calls.append({"app": app, "host": host, "port": port})

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))

    serve_swagger_preview(preview=str(preview_path), host="127.0.0.1", port=8765)

    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8765
    assert "http://127.0.0.1:8765/docs" in capsys.readouterr().out


def test_serve_swagger_preview_increments_unavailable_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The server wrapper opens the next available port when the requested one is busy."""
    from usecaseapi.swagger import serve_swagger_preview

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\n\napi = UseCaseAPI[None]()\n")
    calls: list[dict[str, object]] = []

    def run(app: object, *, host: str, port: int) -> None:
        calls.append({"app": app, "host": host, "port": port})

    def is_port_available(*, host: str, port: int) -> bool:
        return port == 8002

    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=run))
    monkeypatch.setattr("usecaseapi.swagger.is_port_available", is_port_available)

    serve_swagger_preview(preview=str(preview_path), host="127.0.0.1", port=8000)

    assert len(calls) == 1
    assert calls[0]["port"] == 8002
    output = capsys.readouterr().out
    assert "requested port 8000 is unavailable; using 8002" in output
    assert "http://127.0.0.1:8002/docs" in output


def test_select_available_port_reports_exhausted_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Port selection reports an explicit error when no port can be bound."""
    from usecaseapi.swagger import select_available_port

    monkeypatch.setattr("usecaseapi.swagger.is_port_available", lambda *, host, port: False)

    with pytest.raises(SwaggerPreviewError, match="at or above 65535"):
        select_available_port(host="127.0.0.1", preferred_port=65535)


def test_is_port_available_detects_bound_port() -> None:
    """A port already bound by another socket is unavailable."""
    import socket

    from usecaseapi.swagger import is_port_available

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        occupied_port = sock.getsockname()[1]

        assert not is_port_available(host="127.0.0.1", port=occupied_port)


def test_swagger_cli_starts_preview_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The swagger CLI command starts the local preview server with defaults."""
    from usecaseapi.cli import main

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text(
        "from tests.test_swagger_preview import make_bound_api\napi = make_bound_api()\n"
    )
    monkeypatch.chdir(tmp_path)
    called: dict[str, object] = {}

    def fake_serve_swagger_preview(*, preview: str | None, host: str, port: int) -> None:
        called["preview"] = preview
        called["host"] = host
        called["port"] = port

    monkeypatch.setattr("usecaseapi.swagger.serve_swagger_preview", fake_serve_swagger_preview)

    assert main(["swagger"]) == 0
    assert called == {"preview": None, "host": "127.0.0.1", "port": 8000}


def test_swagger_cli_reports_missing_preview_module() -> None:
    """A missing preview module is reported through the CLI error path."""
    from usecaseapi.cli import main

    assert main(["swagger", "--preview", "definitely_missing_preview_module_123"]) == 2


def test_swagger_cli_propagates_unrelated_usecaseapi_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only Swagger preview errors are converted into CLI argument errors."""
    from usecaseapi.cli import main
    from usecaseapi.errors import UseCaseAPIError

    class UnrelatedUseCaseAPIError(UseCaseAPIError):
        """UseCaseAPI error outside the Swagger preview boundary."""

    def fake_serve_swagger_preview(*, preview: str | None, host: str, port: int) -> None:
        raise UnrelatedUseCaseAPIError("internal failure")

    monkeypatch.setattr("usecaseapi.swagger.serve_swagger_preview", fake_serve_swagger_preview)

    with pytest.raises(UnrelatedUseCaseAPIError):
        main(["swagger"])


def test_import_preview_module_rejects_directory_path(tmp_path: Path) -> None:
    """Preview paths must point to Python files."""
    from usecaseapi.swagger import import_preview_module

    with pytest.raises(SwaggerPreviewError, match="is not a file"):
        import_preview_module(str(tmp_path))


def test_import_preview_module_preserves_dependency_import_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Import errors raised by preview module dependencies are not rewritten."""
    from usecaseapi.swagger import import_preview_module

    preview_path = tmp_path / "broken_preview.py"
    preview_path.write_text("import missing_preview_dependency_123\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    with pytest.raises(ModuleNotFoundError, match="missing_preview_dependency_123"):
        import_preview_module("broken_preview")


def test_import_preview_file_reports_missing_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preview file imports fail explicitly when importlib cannot create a loader."""
    from usecaseapi.swagger import import_preview_file

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("from usecaseapi import UseCaseAPI\napi = UseCaseAPI[None]()\n")
    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *args: None)

    with pytest.raises(SwaggerPreviewError, match="could not create import loader"):
        import_preview_file(preview_path)


def test_import_preview_file_removes_failed_module_from_cache(tmp_path: Path) -> None:
    """Failed preview file execution does not leave its temporary module cached."""
    from usecaseapi.swagger import import_preview_file

    preview_path = tmp_path / "usecaseapi_preview.py"
    preview_path.write_text("raise RuntimeError('preview boom')\n")
    cached_before = {
        name for name in sys.modules if name.startswith("_usecaseapi_swagger_preview_")
    }

    with pytest.raises(RuntimeError, match="preview boom"):
        import_preview_file(preview_path)

    cached_after = {name for name in sys.modules if name.startswith("_usecaseapi_swagger_preview_")}
    assert cached_after == cached_before
