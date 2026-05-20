"""Shared Manifest types, constants, and low-level helpers."""
# mypy: ignore-errors

from __future__ import annotations

import ast
import inspect
import keyword
import sys

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from usecaseapi.contracts import UseCaseRef
from usecaseapi.errors import UseCaseError

LEGACY_MANIFEST_KIND = "usecaseapi.manifest/v1"
MANIFEST_PROFILE_KIND = "usecaseapi.openapi.profile/3.1.0"
MANIFEST_KIND = MANIFEST_PROFILE_KIND
MANIFEST_MEDIA_TYPE = "application/vnd.usecaseapi.openapi.profile.v2+yaml"
MANIFEST_EXTENSION = ".yaml"
OPENAPI_VERSION = "3.1.0"
USECASEAPI_PROFILE = "usecaseapi.openapi"
USECASEAPI_VERSION = "3.1.0"
PROTOCOL_KIND = "usecaseapi.inprocess.async_call.v1"
LEGACY_PROTOCOL_KIND = "usecaseapi.inprocess.async_call/v1"

_SCALAR_TYPE_NAMES = {
    "Any",
    "None",
    "str",
    "int",
    "float",
    "bool",
    "bytes",
    "UUID",
    "date",
    "datetime",
    "Decimal",
}
_GENERIC_TYPE_NAMES = {
    "list",
    "dict",
    "set",
    "tuple",
    "Literal",
}
_BUILTIN_TYPE_NAMES = _SCALAR_TYPE_NAMES | _GENERIC_TYPE_NAMES
_SCHEMA_METADATA_KEYS = {
    "default",
    "deprecated",
    "description",
    "examples",
    "readOnly",
    "title",
    "writeOnly",
}
_EMPTY_SCHEMA_KEYS = {"additionalProperties", "items"}
_OPENAPI_OBJECT_MODEL_SCHEMA_KEYS = {
    "additionalProperties",
    "description",
    "properties",
    "required",
    "title",
    "type",
    "x-usecaseapi",
}
_OPENAPI_PATH_ITEM_KEYS = {"post"}
_OPENAPI_OPERATION_KEYS = {
    "deprecated",
    "description",
    "operationId",
    "requestBody",
    "responses",
    "summary",
    "tags",
    "x-usecaseapi",
}
_OPENAPI_REQUEST_BODY_KEYS = {"content", "required"}
_OPENAPI_RESPONSE_KEYS = {"content", "description"}
_OPENAPI_JSON_CONTENT_KEYS = {"application/json"}
_OPENAPI_MEDIA_TYPE_KEYS = {"schema"}
_OPENAPI_OPERATION_EXTENSION_KEYS = {
    "action",
    "bindings",
    "context",
    "errors",
    "input",
    "key",
    "kind",
    "lifecycle",
    "name",
    "output",
    "protocol",
    "semantics",
    "uses",
    "version",
}
_OPENAPI_OPERATION_CONTEXT_KEYS = {"required", "schema", "source"}
_OPENAPI_OPERATION_SEMANTICS = {
    "cacheable": False,
    "idempotent": False,
    "kind": "command",
    "sideEffects": True,
}
_OPENAPI_LIFECYCLE_KEYS = {"deprecated", "stability", "supersededBy"}
_OPENAPI_ROOT_KEYS = {
    "components",
    "info",
    "jsonSchemaDialect",
    "openapi",
    "paths",
    "security",
    "servers",
    "tags",
    "x-usecaseapi",
}
_OPENAPI_COMPONENT_KEYS = {"responses", "schemas"}
_OPENAPI_ROOT_EXTENSION_KEYS = {
    "components",
    "defaults",
    "manifestKind",
    "profile",
    "protocols",
    "runtimes",
    "version",
}
_OPENAPI_ROOT_EXTENSION_COMPONENT_KEYS = {"errors"}
_OPENAPI_RUNTIME_KEYS = {"language", "package", "roots", "version"}
_OPENAPI_RUNTIME_ROOT_KEYS = {"contracts", "implementations", "tests"}
_OPENAPI_JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_JSON_SCHEMA_STRING_FORMATS = {"date", "date-time", "decimal", "uuid"}
_JSON_SCHEMA_PRIMITIVE_TYPES = {"boolean", "integer", "null", "number"}


class ManifestError(ValueError):
    """Raised when a Manifest cannot be parsed, validated, or generated."""


@dataclass(frozen=True, slots=True)
class ManifestScaffoldResult:
    """Files planned or created from a Manifest."""

    files: tuple[Path, ...]
    skipped: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True)
class ManifestDiff:
    """Semantic differences between two Manifest catalogs."""

    breaking: tuple[str, ...]
    warnings: tuple[str, ...]
    additions: tuple[str, ...]

    @property
    def has_breaking_changes(self) -> bool:
        """Whether the diff contains at least one breaking change."""
        return bool(self.breaking)

    def to_dict(self) -> dict[str, list[str]]:
        """Return a JSON-friendly representation."""
        return {
            "breaking": list(self.breaking),
            "warnings": list(self.warnings),
            "additions": list(self.additions),
        }


@dataclass(frozen=True, slots=True)
class ManifestGuardReport:
    """Immutable-version guard result for two UseCaseAPI manifests."""

    removed: tuple[str, ...]
    changed: tuple[str, ...]
    added: tuple[str, ...]

    @property
    def failed(self) -> bool:
        """Whether immutable contract versions were removed or changed."""
        return bool(self.removed or self.changed)

    def to_dict(self) -> dict[str, list[str] | bool]:
        """Return a JSON-friendly representation."""
        return {
            "failed": self.failed,
            "removed": list(self.removed),
            "changed": list(self.changed),
            "added": list(self.added),
        }


@dataclass(frozen=True, slots=True)
class ContractCheckReport:
    """Result of validating one committed UseCaseAPI manifest."""

    manifest: str
    target: str
    manifest_valid: bool
    synchronized: bool
    guard: ManifestGuardReport | None
    errors: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        """Whether the contract check should fail CI."""
        return bool(
            self.errors
            or not self.manifest_valid
            or not self.synchronized
            or (self.guard is not None and self.guard.failed)
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly report."""
        return {
            "status": "failed" if self.failed else "passed",
            "manifest": self.manifest,
            "target": self.target,
            "validation": {
                "manifest": "passed" if self.manifest_valid else "failed",
                "sync": "passed" if self.synchronized else "failed",
            },
            "guard": self.guard.to_dict() if self.guard is not None else None,
            "errors": list(self.errors),
        }


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


def subscript_args(node: ast.AST) -> list[ast.AST]:
    """Return subscript arguments across Python AST tuple and scalar forms."""
    if isinstance(node, ast.Tuple):
        return list(node.elts)
    return [node]


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


def manifest_models(usecase: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read Manifest model mappings."""
    value = usecase.get("models")
    if not isinstance(value, list) or not value:
        raise ManifestError("usecase.models must be a non-empty list")
    return [required_mapping(item, "model") for item in value]


def manifest_errors(usecase: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read Manifest error mappings."""
    value = usecase.get("errors", [])
    if not isinstance(value, list):
        raise ManifestError("usecase.errors must be a list")
    return [required_mapping(item, "error") for item in value]


def manifest_fields(container: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read Manifest field mappings."""
    value = container.get("fields", [])
    if not isinstance(value, list):
        raise ManifestError("fields must be a list")
    return [required_mapping(item, "field") for item in value]


def usecase_items(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read Manifest usecase mappings."""
    if manifest.get("kind") == LEGACY_MANIFEST_KIND or "usecases" in manifest:
        value = manifest.get("usecases")
    else:
        from .validation import semantic_from_openapi_manifest

        value = semantic_from_openapi_manifest(manifest).get("usecases")
    if not isinstance(value, list):
        raise ManifestError("manifest.usecases must be a list")
    return [required_mapping(item, "usecase") for item in value]


def usecase_items_from_semantic(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Read already-normalized semantic usecase mappings."""
    value = manifest.get("usecases")
    if not isinstance(value, list):
        raise ManifestError("manifest.usecases must be a list")
    return [required_mapping(item, "usecase") for item in value]


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


def default_contract_file(usecase: Mapping[str, Any], *, contracts_root: str) -> str:
    """Return the default generated contract file path."""
    name = required_string(usecase, "name")
    version = required_int(usecase, "version")
    parts = name.split(".")
    return str(Path(contracts_root) / Path(*parts[:-1]) / parts[-1] / f"v{version}.py")


def default_implementation_file(usecase: Mapping[str, Any], *, implementations_root: str) -> str:
    """Return the default generated implementation file path."""
    name = required_string(usecase, "name")
    parts = name.split(".")
    return str(Path(implementations_root) / Path(*parts[:-1]) / f"{parts[-1]}.py")


def default_manifest_test_file(usecase: Mapping[str, Any], *, tests_root: str) -> str:
    """Return the default generated pytest file path for a Manifest usecase."""
    name = required_string(usecase, "name")
    version = required_int(usecase, "version")
    parts = name.split(".")
    return str(
        Path(tests_root) / Path(*parts[:-1]) / parts[-1] / f"v{version}" / f"test_{parts[-1]}.py"
    )


def module_from_python_file(path: Path, *, package: str | None) -> str:
    """Return an import module for a generated Python file."""
    parts = list(path.with_suffix("").parts)
    if package is not None and package in parts:
        parts = parts[parts.index(package) :]
    return ".".join(parts)


def default_implementation_class(name: str) -> str:
    """Return the default v1.1 implementation class name for exported source metadata."""
    return "".join(part.capitalize() for part in name.split(".")[-1].split("_")) + "UseCase"


def default_implementation_path(
    name: str,
    *,
    version: int,
    implementations_root: str,
    package: str | None,
) -> str:
    """Return the default implementation path for exported source metadata."""
    parts = name.split(".")
    if package is not None and parts[0] == package:
        package_name = package
        usecase_parts = parts[1:]
    else:
        package_name = parts[0]
        usecase_parts = parts[1:]
    usecase_name = parts[-1]
    return str(
        Path(implementations_root)
        / package_name
        / "usecases"
        / Path(*usecase_parts)
        / f"v{version}"
        / f"{usecase_name}_usecase.py"
    )


def write_generated_file(path: Path, content: str, *, force: bool, dry_run: bool) -> None:
    """Write a generated file unless dry-run or protected by force."""
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass force=True to overwrite")
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def ensure_init_files(directory: Path, *, stop_at: Path) -> None:
    """Create package __init__.py files up to a boundary."""
    current = directory
    stop = stop_at.resolve()
    while True:
        if current.resolve() == stop or current.parent == current:
            break
        init_file = current / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""Generated package."""\n')
        current = current.parent


def source_file(value: Any) -> str | None:
    """Return a source file path for an inspected object when available."""
    try:
        file_name = inspect.getsourcefile(value)
    except TypeError:
        return None
    if file_name is None:
        return None
    path = Path(file_name).resolve()
    try:
        return path.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def trim_to_root(file_path: str, root: str) -> str:
    """Trim a source path so it starts at the configured root."""
    path_parts = Path(file_path).parts
    root_parts = Path(root).parts
    if not root_parts:
        return file_path
    for index in range(0, len(path_parts) - len(root_parts) + 1):
        if path_parts[index : index + len(root_parts)] == root_parts:
            return str(Path(*path_parts[index:]))
    return file_path


def qualname(value: object) -> str:
    """Return a stable module-qualified name when available."""
    module = getattr(value, "__module__", None)
    qualname = getattr(value, "__qualname__", None)
    if isinstance(module, str) and isinstance(qualname, str):
        return f"{module}.{qualname}"
    return repr(value)


def find_ref_symbol(ref: UseCaseRef[Any, Any]) -> str | None:
    """Find the symbol name that exports a UseCaseRef."""
    module = sys.modules.get(ref.protocol.__module__)
    if module is None:
        return None
    for name, value in vars(module).items():
        if value is ref and name.isidentifier():
            return name
    return None


def default_ref_symbol(name: str) -> str:
    """Return the default constant name for a contract."""
    return name.split(".")[-1].upper()


def class_name(error_type: type[UseCaseError]) -> str:
    """Return the class name for an error type."""
    return error_type.__name__


def valid_contract_name(name: str) -> bool:
    """Return whether a contract name is valid."""
    parts = name.split(".")
    return len(parts) >= 2 and all(
        valid_python_identifier(part) and part.islower() for part in parts
    )


def valid_key(key: str) -> bool:
    """Return whether a usecase key is valid."""
    if "@v" not in key:
        return False
    name, _, version = key.partition("@v")
    return valid_contract_name(name) and version.isdigit() and int(version) >= 1


def valid_module_path(value: str) -> bool:
    """Return whether a dotted Python module path is valid."""
    return bool(value) and all(valid_python_identifier(part) for part in value.split("."))


def valid_python_identifier(value: str) -> bool:
    """Return whether a value is a Python identifier that can be generated safely."""
    return value.isidentifier() and not keyword.iskeyword(value)


def error_extends(error_name: str, base_name: str, base_by_name: Mapping[str, str]) -> bool:
    """Return whether one error extends another by Manifest metadata."""
    current = error_name
    while current != "UseCaseError":
        if current == base_name:
            return True
        current = base_by_name.get(current, "UseCaseError")
    return base_name == "UseCaseError"


def required_string(mapping: Mapping[str, Any], key: str) -> str:
    """Read a required non-empty string field."""
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ManifestError(f"{key} must be a non-empty string")
    return value


def required_int(mapping: Mapping[str, Any], key: str) -> int:
    """Read a required integer field."""
    value = mapping.get(key)
    if not isinstance(value, int):
        raise ManifestError(f"{key} must be an integer")
    return value


def string_or_default(value: object, default: str) -> str:
    """Read a non-empty string or return a default."""
    return value if isinstance(value, str) and value else default


def string_list(value: object) -> list[str]:
    """Read a list of strings, rejecting malformed values."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ManifestError("expected a list of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ManifestError("expected a list of strings")
        result.append(item)
    return result


def required_mapping(value: object, name: str) -> Mapping[str, Any]:
    """Read a required mapping value."""
    if not isinstance(value, Mapping):
        raise ManifestError(f"{name} must be a mapping")
    return value


def without_none(value: dict[str, Any], *, preserve_empty: bool = False) -> dict[str, Any]:
    """Return a copy without None values, including nested mappings."""
    result: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            nested = without_none(item, preserve_empty=preserve_empty or key == "properties")
            if nested or key == "properties" or key in _EMPTY_SCHEMA_KEYS or preserve_empty:
                result[key] = nested
        elif item is not None:
            result[key] = item
    return result


def usecase_key(usecase: Mapping[str, Any]) -> str:
    """Return the canonical key for a Manifest usecase."""
    return string_or_default(
        usecase.get("key"),
        f"{required_string(usecase, 'name')}@v{required_int(usecase, 'version')}",
    )


def pascal_identifier(value: str) -> str:
    """Return a PascalCase identifier fragment from snake_case or dotted names."""
    return "".join(part.capitalize() for part in value.split("_"))


def node_id(key: str) -> str:
    """Return a Mermaid-safe node identifier."""
    return "uc_" + "".join(character if character.isalnum() else "_" for character in key)


def index_usecases(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Index Manifest usecases by key."""
    return {usecase_key(item): item for item in usecase_items(manifest)}


def model_map(usecase: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return comparable model field metadata keyed by model name."""
    return {
        required_string(model, "name"): [
            dict(field)
            for field in sorted(
                manifest_fields(model), key=lambda field: required_string(field, "name")
            )
        ]
        for model in manifest_models(usecase)
    }


def error_map(usecase: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return comparable error metadata keyed by error name."""
    return {
        required_string(error, "name"): {
            "base": string_or_default(error.get("base"), "UseCaseError"),
            "code": required_string(error, "code"),
            "fields": [
                dict(field)
                for field in sorted(
                    manifest_fields(error), key=lambda field: required_string(field, "name")
                )
            ],
        }
        for error in manifest_errors(usecase)
    }


def model_field_changes(old_case: Mapping[str, Any], new_case: Mapping[str, Any]) -> bool:
    """Return whether model names or fields changed."""
    old_models = model_map(old_case)
    new_models = model_map(new_case)
    for name in reachable_model_names(old_case, old_models):
        old_fields = old_models[name]
        if name not in new_models or new_models[name] != old_fields:
            return True
    return False


def reachable_model_names(
    usecase: Mapping[str, Any],
    models: Mapping[str, Sequence[Mapping[str, Any]]],
) -> set[str]:
    """Return model names reachable from the input and output contract boundary."""
    pending = [required_string(usecase, "input"), required_string(usecase, "output")]
    for error in manifest_errors(usecase):
        for field in manifest_fields(error):
            pending.extend(model_names_from_type_expr(required_string(field, "type"), models))
    reachable: set[str] = set()
    while pending:
        name = pending.pop()
        if name in reachable or name not in models:
            continue
        reachable.add(name)
        for field in models[name]:
            pending.extend(model_names_from_type_expr(required_string(field, "type"), models))
    return reachable


def model_names_from_type_expr(
    expr: str,
    models: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[str, ...]:
    """Return manifest model names referenced by a supported type expression."""
    parsed = ast.parse(expr, mode="eval").body
    found: list[str] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            if node.id in models:
                found.append(node.id)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(parsed)
    return tuple(found)


def semantic_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return the semantic subset used for sync comparison."""
    from .validation import validate_manifest

    validate_manifest(manifest)
    return {
        "kind": LEGACY_MANIFEST_KIND,
        "usecases": [
            {
                "name": required_string(item, "name"),
                "version": required_int(item, "version"),
                "key": usecase_key(item),
                "description": item.get("description"),
                "stable": item.get("stable", True),
                "deprecated": item.get("deprecated", False),
                "superseded_by": item.get("superseded_by"),
                "tags": string_list(item.get("tags")),
                "input": required_string(item, "input"),
                "output": required_string(item, "output"),
                "models": model_map(item),
                "errors": error_map(item),
                "raises": string_list(item.get("raises")),
                "known_errors": string_list(item.get("known_errors")),
                "uses": string_list(item.get("uses")),
            }
            for item in usecase_items(manifest)
        ],
    }


def project_name(manifest: Mapping[str, Any]) -> str | None:
    """Read Manifest project name when present."""
    if manifest.get("openapi") == OPENAPI_VERSION:
        info = manifest.get("info")
        name = info.get("title") if isinstance(info, Mapping) else None
    else:
        name = project_name_from_semantic(manifest)
    if isinstance(name, str):
        return name
    return None


def project_name_from_semantic(manifest: Mapping[str, Any]) -> str | None:
    """Read semantic Manifest project name when present."""
    metadata = manifest.get("metadata")
    name = metadata.get("name") if isinstance(metadata, Mapping) else None
    if isinstance(name, str):
        return name
    return None


def package_name(manifest: Mapping[str, Any]) -> str | None:
    """Read Manifest package name when present."""
    if manifest.get("openapi") == OPENAPI_VERSION:
        from .validation import semantic_from_openapi_manifest

        layout = semantic_from_openapi_manifest(manifest).get("layout")
    else:
        layout = manifest.get("layout")
    package = layout.get("package") if isinstance(layout, Mapping) else None
    if isinstance(package, str):
        return package
    return None


__all__ = [name for name in globals() if not name.startswith("__")]
