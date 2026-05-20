"""Python scaffold rendering helpers for Manifest metadata."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

import ast

from collections.abc import Mapping, Sequence
from typing import Any

from .accessors import *
from .common import *
from .helpers import *
from .semantic_validation import *


def render_model_class(model: Mapping[str, Any]) -> list[str]:
    """Render a Model class from Manifest metadata."""
    name = required_string(model, "name")
    fields = manifest_fields(model)
    lines = [f"class {name}(Model):"]
    description = model.get("description")
    if isinstance(description, str) and description:
        lines.append(f"    {py_string_literal(description)}")
        lines.append("")
    if not fields:
        lines.append("    pass")
        return lines
    for field in fields:
        type_expr, default = render_scaffold_field(field, context=f"model {name}")
        lines.append(f"    {required_string(field, 'name')}: {type_expr}{default}")
    return lines


def render_scaffold_field(field: Mapping[str, Any], *, context: str) -> tuple[str, str]:
    """Return a field annotation and default without widening the Manifest contract."""
    field_name = required_string(field, "name")
    type_expr = required_string(field, "type")
    required = bool(field.get("required", True))
    if required:
        return type_expr, ""
    if not type_expr_allows_none(type_expr):
        raise ManifestError(
            f"{context}.{field_name} is optional but non-nullable; scaffold cannot preserve "
            "that contract"
        )
    return type_expr, " = None"


def render_error_class(error: Mapping[str, Any]) -> list[str]:
    """Render a UseCaseError class from Manifest metadata."""
    name = required_string(error, "name")
    base = string_or_default(error.get("base"), "UseCaseError")
    code = required_string(error, "code")
    description = error.get("description")
    class_description = (
        description if isinstance(description, str) and description else f"Domain error for {code}."
    )
    fields = manifest_fields(error)
    lines = [
        f"class {name}({base}):",
        f"    {py_string_literal(class_description)}",
        "",
        f"    code: ClassVar[str] = {py_string_literal(code)}",
    ]
    if not fields:
        return lines
    lines.append("")
    for field in fields:
        lines.append(f"    {required_string(field, 'name')}: {required_string(field, 'type')}")
    lines.append("")
    params = ", ".join(render_error_init_param(field, context=f"error {name}") for field in fields)
    lines.append(f"    def __init__(self, *, {params}) -> None:")
    lines.append(f"        {py_string_literal(f'Create a {name} domain error.')}")
    for field in fields:
        field_name = required_string(field, "name")
        lines.append(f"        self.{field_name} = {field_name}")
    lines.append(f"        super().__init__({py_string_literal(code)})")
    return lines


def render_error_init_param(field: Mapping[str, Any], *, context: str) -> str:
    """Render an error constructor parameter without changing optional/null semantics."""
    field_name = required_string(field, "name")
    type_expr, default = render_scaffold_field(field, context=context)
    return f"{field_name}: {type_expr}{default}"


def collect_type_exprs(
    models: Sequence[Mapping[str, Any]],
    errors: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Collect all field type expressions used by generated code."""
    exprs: list[str] = []
    for container in (*models, *errors):
        for field in manifest_fields(container):
            exprs.append(required_string(field, "type"))
    return exprs


def typing_imports(
    type_exprs: Sequence[str],
    errors: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Return typing imports required by generated code."""
    imports = ["Protocol"]
    if errors:
        imports.append("ClassVar")
    if any("Literal[" in expr for expr in type_exprs):
        imports.append("Literal")
    if any(type_expr_contains_name(expr, "Any") for expr in type_exprs):
        imports.append("Any")
    return sorted(set(imports))


def usecaseapi_imports(errors: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return usecaseapi imports required by generated code."""
    imports = ["Contract", "Model", "UseCase", "UseCaseRef", "define_usecase"]
    if errors:
        imports.insert(3, "UseCaseError")
    return imports


def render_contract_binding(
    *,
    protocol_class: str,
    input_name: str,
    output_name: str,
    ref: str,
    name: str,
    version: int,
    raises: Sequence[str],
    known_errors: Sequence[str],
    stable: bool,
    deprecated: bool,
    superseded_by: object,
    description: object,
    tags: Sequence[str],
) -> list[str]:
    """Render protocol and UseCaseRef binding code."""
    protocol_description = (
        description
        if isinstance(description, str)
        else (f"Contract Protocol for {name} v{version}.")
    )
    lines = [
        f"class {protocol_class}(UseCase[{input_name}, {output_name}], Protocol):",
        f"    {py_string_literal(protocol_description)}",
        "",
        f"    async def __call__(self, input: {input_name}, /) -> {output_name}:",
        f"        {py_string_literal(f'Run {name} v{version}.')}",
        "        ...",
        "",
        "",
        f"{ref}: UseCaseRef[{input_name}, {output_name}] = define_usecase(",
        f"    {protocol_class},",
        "    Contract(",
        f"        name={py_string_literal(name)},",
        f"        version={version},",
        f"        input={input_name},",
        f"        output={output_name},",
        f"        raises={tuple_expr(raises)},",
        f"        known_errors={tuple_expr(known_errors)},",
        f"        stable={stable!r},",
        f"        deprecated={deprecated!r},",
    ]
    lines.extend(optional_contract_metadata_lines(superseded_by, description, tags))
    lines.extend(["    ),", ")", ""])
    return lines


def optional_contract_metadata_lines(
    superseded_by: object,
    description: object,
    tags: Sequence[str],
) -> list[str]:
    """Render optional Contract keyword lines."""
    lines: list[str] = []
    if isinstance(superseded_by, str):
        lines.append(f"        superseded_by={superseded_by!r},")
    if isinstance(description, str):
        lines.append(f"        description={description!r},")
    if tags:
        lines.append(f"        tags={tuple(tags)!r},")
    return lines


def py_string_literal(value: str) -> str:
    """Render a Python string literal for generated source."""
    return repr(value)


def stdlib_import_lines(type_exprs: Sequence[str]) -> list[str]:
    """Render standard-library imports required by type expressions."""
    lines: list[str] = []
    if any(type_expr_contains_name(expr, "UUID") for expr in type_exprs):
        lines.append("from uuid import UUID")
    datetime_names = [
        name
        for name in ("date", "datetime")
        if any(type_expr_contains_name(expr, name) for expr in type_exprs)
    ]
    if datetime_names:
        lines.append("from datetime import " + ", ".join(sorted(set(datetime_names))))
    if any(type_expr_contains_name(expr, "Decimal") for expr in type_exprs):
        lines.append("from decimal import Decimal")
    if lines:
        lines.append("")
    return lines


def type_expr_contains_name(expr: str, name: str) -> bool:
    """Return whether a type expression references a name."""
    try:
        parsed = ast.parse(expr, mode="eval")
    except SyntaxError:
        return False
    return any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(parsed))


def tuple_expr(names: Sequence[str]) -> str:
    """Render names as a Python tuple expression."""
    if not names:
        return "()"
    return "(" + ", ".join(names) + ",)"


__all__ = [name for name in globals() if not name.startswith("__")]
