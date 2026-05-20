"""Semantic Manifest validation helpers."""

from __future__ import annotations

import ast

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from usecaseapi.manifest_domain.common import (
    _BUILTIN_TYPE_NAMES,
    _GENERIC_TYPE_NAMES,
    ManifestError,
)
from usecaseapi.manifest_domain.semantic.accessors import (
    manifest_errors,
    manifest_fields,
    manifest_models,
)
from usecaseapi.manifest_domain.shared.helpers import (
    error_extends,
    module_from_python_file,
    required_int,
    required_mapping,
    required_string,
    string_list,
    string_or_default,
    subscript_args,
    valid_contract_name,
    valid_key,
    valid_module_path,
    valid_python_identifier,
)


def validate_usecase_manifest(
    item: Mapping[str, Any],
    *,
    seen_keys: set[str],
    index: int,
) -> None:
    """Validate one Manifest usecase entry."""
    key = validate_usecase_identity(item, seen_keys=seen_keys, index=index)
    validate_source(item, index=index)
    validate_models(item, index=index)
    error_base_by_name = validate_errors(item)
    validate_type_references(item)
    validate_error_boundaries(item, error_base_by_name)
    validate_uses(item, key=key)


def validate_usecase_identity(
    item: Mapping[str, Any],
    *,
    seen_keys: set[str],
    index: int,
) -> str:
    """Validate usecase name, version, and canonical key identity."""
    name = required_string(item, "name")
    if not valid_contract_name(name):
        raise ManifestError(f"usecases[{index}].name must look like 'package.use_case'")
    if "domain" in item:
        raise ManifestError(f"usecases[{index}].domain is not supported; use layout.package")
    version = required_int(item, "version")
    if version < 1:
        raise ManifestError(f"usecases[{index}].version must be >= 1")
    key = string_or_default(item.get("key"), f"{name}@v{version}")
    if key != f"{name}@v{version}":
        raise ManifestError(f"usecases[{index}].key must be '{name}@v{version}'")
    if key in seen_keys:
        raise ManifestError(f"duplicate usecase key {key!r}")
    seen_keys.add(key)
    return key


def validate_source(item: Mapping[str, Any], *, index: int) -> None:
    """Validate source mapping for one usecase."""
    source = required_mapping(item.get("source"), f"usecases[{index}].source")
    for field_name in ("contract_module", "protocol_class", "ref"):
        value = required_string(source, field_name)
        if field_name == "contract_module":
            if not valid_module_path(value):
                raise ManifestError(f"usecases[{index}].source.contract_module is invalid")
        elif not valid_python_identifier(value):
            raise ManifestError(f"usecases[{index}].source.{field_name} must be an identifier")
    implementation_class = source.get("implementation_class")
    if isinstance(implementation_class, str) and implementation_class:
        if not valid_python_identifier(implementation_class):
            raise ManifestError(
                f"usecases[{index}].source.implementation_class must be an identifier"
            )
    for field_name in ("contract_file", "implementation_file"):
        file_path = source.get(field_name)
        if isinstance(file_path, str) and file_path:
            validate_manifest_file_path(file_path, context=f"usecases[{index}].source.{field_name}")


def validate_manifest_file_path(value: str, *, context: str) -> None:
    """Validate a Manifest-provided generated Python file path."""
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ManifestError(f"{context} must not contain empty, current, or parent segments")
    path = Path(value)
    if path.is_absolute():
        raise ManifestError(f"{context} must be a relative path")
    if path.suffix != ".py":
        raise ManifestError(f"{context} must end with .py")
    module_parts = list(path.with_suffix("").parts)
    for part in module_parts:
        if not valid_python_identifier(part):
            raise ManifestError(f"{context} contains invalid Python module segment {part!r}")


def validate_contract_file_module(
    contract_path: str,
    contract_module: str,
    *,
    package: str | None,
) -> None:
    """Validate that an explicit contract file maps to the declared contract module."""
    file_module = module_from_python_file(Path(contract_path), package=package)
    if file_module != contract_module:
        raise ManifestError(
            "source.contract_file must map to source.contract_module "
            f"({file_module!r} != {contract_module!r})"
        )


def validate_models(item: Mapping[str, Any], *, index: int) -> None:
    """Validate model declarations for one usecase."""
    input_name = required_string(item, "input")
    output_name = required_string(item, "output")
    if not valid_python_identifier(input_name) or not valid_python_identifier(output_name):
        raise ManifestError(f"usecases[{index}].input/output must be identifiers")

    model_names: set[str] = set()
    for model in manifest_models(item):
        model_name = required_string(model, "name")
        if not valid_python_identifier(model_name):
            raise ManifestError(f"model name must be an identifier: {model_name!r}")
        if model_name in model_names:
            raise ManifestError(f"duplicate model name {model_name!r}")
        model_names.add(model_name)
        for field in manifest_fields(model):
            validate_field(field, context=f"model {model_name}")
    if input_name not in model_names:
        raise ManifestError(f"input model {input_name!r} is not defined in models")
    if output_name not in model_names:
        raise ManifestError(f"output model {output_name!r} is not defined in models")


def validate_errors(item: Mapping[str, Any]) -> dict[str, str]:
    """Validate error declarations and return base metadata by name."""
    errors = manifest_errors(item)
    error_names: set[str] = {"UseCaseError"}
    error_base_by_name: dict[str, str] = {}
    for error in errors:
        error_name = required_string(error, "name")
        if not valid_python_identifier(error_name):
            raise ManifestError(f"error name must be an identifier: {error_name!r}")
        if error_name in error_names:
            raise ManifestError(f"duplicate error name {error_name!r}")
        required_string(error, "code")
        base = string_or_default(error.get("base"), "UseCaseError")
        error_names.add(error_name)
        error_base_by_name[error_name] = base
        for field in manifest_fields(error):
            validate_field(field, context=f"error {error_name}")
    for error_name, base in error_base_by_name.items():
        if base not in error_names:
            raise ManifestError(f"error {error_name} extends unknown base {base!r}")
    return error_base_by_name


def validate_error_boundaries(
    item: Mapping[str, Any],
    error_base_by_name: Mapping[str, str],
) -> None:
    """Validate raises and known_errors against declared errors."""
    raises = string_list(item.get("raises"))
    known_errors = string_list(item.get("known_errors"))
    error_names = {"UseCaseError", *error_base_by_name}
    for name_value in (*raises, *known_errors):
        if name_value not in error_names:
            raise ManifestError(f"declared error {name_value!r} is not defined in errors")
    for known_error in known_errors:
        if raises and not any(
            error_extends(known_error, raised, error_base_by_name) for raised in raises
        ):
            raise ManifestError(f"known error {known_error!r} is not covered by raises")


def validate_type_references(item: Mapping[str, Any]) -> None:
    """Validate that user-defined field types reference declared models."""
    model_names = {required_string(model, "name") for model in manifest_models(item)}
    for model in manifest_models(item):
        model_name = required_string(model, "name")
        for field in manifest_fields(model):
            validate_type_expr_references(
                required_string(field, "type"),
                model_names=model_names,
                context=f"model {model_name}",
            )
    for error in manifest_errors(item):
        error_name = required_string(error, "name")
        for field in manifest_fields(error):
            validate_type_expr_references(
                required_string(field, "type"),
                model_names=model_names,
                context=f"error {error_name}",
            )


def validate_type_expr_references(
    expr: str,
    *,
    model_names: set[str],
    context: str,
) -> None:
    """Validate model references inside one supported type expression."""
    parsed = ast.parse(expr, mode="eval").body

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            if node.id in _GENERIC_TYPE_NAMES:
                raise ManifestError(
                    f"generic type requires type arguments in {context}: {node.id!r}"
                )
            if node.id not in _BUILTIN_TYPE_NAMES and node.id not in model_names:
                raise ManifestError(f"unknown model type {node.id!r} in {context}")
            return
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id in _GENERIC_TYPE_NAMES:
                if node.value.id == "Literal":
                    return
                visit(node.slice)
                return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(parsed)


def validate_uses(item: Mapping[str, Any], *, key: str) -> None:
    """Validate declared dependency keys."""
    for use_key in string_list(item.get("uses")):
        if not valid_key(use_key):
            raise ManifestError(f"invalid uses key {use_key!r}")
        if use_key == key:
            raise ManifestError(f"usecase {key!r} cannot use itself")


def validate_type_expr(expr: str) -> None:
    """Validate UseCaseAPI's Python-annotation-compatible type expression subset."""
    try:
        parsed = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ManifestError(f"invalid type expression {expr!r}") from exc
    validate_type_ast(parsed.body, expr=expr)


def type_expr_allows_none(expr: str) -> bool:
    """Return whether a supported type expression admits an explicit None value."""
    validate_type_expr(expr)
    parsed = ast.parse(expr, mode="eval").body

    return top_level_type_ast_allows_none(parsed)


def top_level_type_ast_allows_none(node: ast.AST) -> bool:
    """Return whether a top-level type AST admits None as the field value itself."""
    if isinstance(node, ast.Name):
        return node.id == "Any"
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return top_level_type_ast_allows_none(node.left) or top_level_type_ast_allows_none(
            node.right
        )
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
        if node.value.id == "Literal":
            return any(
                isinstance(arg, ast.Constant) and arg.value is None
                for arg in subscript_args(node.slice)
            )
        return False
    return False


def validate_type_ast(node: ast.AST, *, expr: str) -> None:
    """Validate an AST node for the supported type expression subset."""
    if isinstance(node, ast.Name):
        if node.id in _GENERIC_TYPE_NAMES:
            raise ManifestError(f"generic type requires type arguments in {expr!r}: {node.id!r}")
        if not (node.id in _BUILTIN_TYPE_NAMES or node.id.isidentifier()):
            raise ManifestError(f"invalid type name in {expr!r}: {node.id!r}")
        return
    if isinstance(node, ast.Constant):
        if node.value is None:
            return
        raise ManifestError(f"invalid literal in {expr!r}")
    if isinstance(node, ast.Subscript):
        validate_subscript_type_ast(node, expr=expr)
        return
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        validate_type_ast(node.left, expr=expr)
        validate_type_ast(node.right, expr=expr)
        return
    raise ManifestError(f"unsupported type expression syntax in {expr!r}")


def validate_subscript_type_ast(node: ast.Subscript, *, expr: str) -> None:
    """Validate supported generic type expression shapes."""
    if not isinstance(node.value, ast.Name) or node.value.id not in _GENERIC_TYPE_NAMES:
        raise ManifestError(f"unsupported generic type in {expr!r}")

    name = node.value.id
    args = subscript_args(node.slice)
    if name in {"list", "set"}:
        validate_single_argument_generic(name, args, expr=expr)
        return
    if name == "dict":
        validate_dict_generic(args, expr=expr)
        return
    if name == "tuple":
        validate_tuple_generic(args, expr=expr)
        return
    if name == "Literal":
        validate_literal_generic(args)
        return


def validate_single_argument_generic(name: str, args: Sequence[ast.AST], *, expr: str) -> None:
    """Validate list[T] and set[T] type expressions."""
    if len(args) != 1:
        raise ManifestError(f"generic type {name!r} requires exactly one argument")
    validate_type_ast(args[0], expr=expr)


def validate_dict_generic(args: Sequence[ast.AST], *, expr: str) -> None:
    """Validate dict[str, T] type expressions."""
    if len(args) != 2:
        raise ManifestError("generic type 'dict' requires exactly two arguments")
    if not (isinstance(args[0], ast.Name) and args[0].id == "str"):
        raise ManifestError("generic type 'dict' requires a str key type")
    validate_type_ast(args[1], expr=expr)


def validate_tuple_generic(args: Sequence[ast.AST], *, expr: str) -> None:
    """Validate tuple[T, U] type expressions."""
    if not args:
        raise ManifestError("generic type 'tuple' requires at least one argument")
    for arg in args:
        validate_type_ast(arg, expr=expr)


def validate_literal_generic(args: Sequence[ast.AST]) -> None:
    """Validate Literal[...] type expressions."""
    if not args:
        raise ManifestError("Literal values require at least one argument")
    for arg in args:
        if not is_supported_literal_value(arg):
            raise ManifestError("Literal values must be string, integer, float, boolean, or None")


def is_supported_literal_value(node: ast.AST) -> bool:
    """Return whether an AST node is a supported Literal[...] value."""
    if not isinstance(node, ast.Constant):
        return False
    return is_supported_literal_value_object(node.value)


def is_supported_literal_value_object(value: object) -> bool:
    """Return whether a JSON value is supported by Literal[...] fields."""
    return isinstance(value, str | int | float | bool) or value is None


def validate_field(field: Mapping[str, Any], *, context: str) -> None:
    """Validate one Manifest model or error field."""
    field_name = required_string(field, "name")
    if not valid_python_identifier(field_name):
        raise ManifestError(f"{context} field name must be an identifier: {field_name!r}")
    validate_type_expr(required_string(field, "type"))
    required = field.get("required", True)
    if not isinstance(required, bool):
        raise ManifestError(f"{context}.{field_name}.required must be a boolean")
