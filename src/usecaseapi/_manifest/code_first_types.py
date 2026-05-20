"""Code-first model, error, and annotation conversion helpers."""
# ruff: noqa: F403,F405
# mypy: ignore-errors

from __future__ import annotations

import types

from typing import Any, ClassVar, Literal, Union, get_args, get_origin, get_type_hints

from pydantic.fields import FieldInfo

from usecaseapi.errors import UseCaseError
from usecaseapi.model import Model

from .common import *


def model_to_manifest(model_type: type[Model]) -> dict[str, Any]:
    """Convert a Model class into Manifest model metadata."""
    validate_representable_model(model_type)
    item: dict[str, Any] = {
        "name": model_type.__name__,
        "module": model_type.__module__,
        "fields": [
            field_to_manifest(name, field) for name, field in model_type.model_fields.items()
        ],
    }
    description = inspect.getdoc(model_type)
    if description is not None:
        item["description"] = description
    return item


def validate_representable_model(model_type: type[Model]) -> None:
    """Reject Pydantic model behavior the Manifest cannot preserve."""
    base_config = dict(Model.model_config)
    model_config = dict(model_type.model_config)
    if model_config != base_config:
        raise ManifestError(
            f"model {model_type.__qualname__!r} uses unsupported Pydantic model_config"
        )
    decorators = getattr(model_type, "__pydantic_decorators__", None)
    if decorators is None:
        return
    unsupported_decorators = {
        "validators": getattr(decorators, "validators", None),
        "field_validators": getattr(decorators, "field_validators", None),
        "root_validators": getattr(decorators, "root_validators", None),
        "model_validators": getattr(decorators, "model_validators", None),
        "field_serializers": getattr(decorators, "field_serializers", None),
        "model_serializers": getattr(decorators, "model_serializers", None),
        "computed_fields": getattr(decorators, "computed_fields", None),
    }
    present = sorted(name for name, values in unsupported_decorators.items() if values)
    if present:
        raise ManifestError(
            f"model {model_type.__qualname__!r} uses unsupported Pydantic decorators: {present!r}"
        )


def field_to_manifest(name: str, field: FieldInfo) -> dict[str, Any]:
    """Convert a Pydantic field into Manifest field metadata."""
    validate_representable_field(name, field)
    item: dict[str, Any] = {
        "name": name,
        "type": format_annotation(field.annotation),
        "required": field.is_required(),
    }
    if field.description is not None:
        item["description"] = field.description
    return item


def validate_representable_field(name: str, field: FieldInfo) -> None:
    """Reject Pydantic field metadata that the Manifest cannot preserve."""
    aliases = {
        "alias": field.alias,
        "validation_alias": field.validation_alias,
        "serialization_alias": field.serialization_alias,
    }
    for alias_name, alias_value in aliases.items():
        if alias_value is not None and alias_value != name:
            raise ManifestError(f"field {name!r} uses unsupported Pydantic {alias_name}")
    if field.default_factory is not None:
        raise ManifestError(f"field {name!r} uses an unsupported default_factory")
    if not field.is_required() and field.default is not None:
        raise ManifestError(f"field {name!r} uses an unsupported non-None default")
    if field.metadata:
        raise ManifestError(f"field {name!r} uses unsupported Pydantic constraints")
    if field.json_schema_extra is not None:
        raise ManifestError(f"field {name!r} uses unsupported JSON Schema extras")
    if field.title is not None:
        raise ManifestError(f"field {name!r} uses an unsupported schema title")
    if field.examples is not None:
        raise ManifestError(f"field {name!r} uses unsupported schema examples")
    if field.deprecated is not None:
        raise ManifestError(f"field {name!r} uses unsupported deprecation metadata")


def error_to_manifest(error_type: type[UseCaseError]) -> dict[str, Any]:
    """Convert a UseCaseError class into Manifest error metadata."""
    bases = [base for base in error_type.__bases__ if issubclass(base, UseCaseError)]
    base_name = bases[0].__name__ if bases else "UseCaseError"
    item: dict[str, Any] = {
        "name": error_type.__name__,
        "module": error_type.__module__,
        "base": base_name,
        "code": getattr(error_type, "code", ""),
        "fields": error_fields(error_type),
    }
    description = inspect.getdoc(error_type)
    if description is not None:
        item["description"] = description
    return item


def error_fields(error_type: type[UseCaseError]) -> list[dict[str, Any]]:
    """Extract public constructor and annotated fields from an error class."""
    try:
        hints = get_type_hints(error_type)
    except (NameError, TypeError):
        hints = getattr(error_type, "__annotations__", {})
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, annotation in hints.items():
        if name == "code" or get_origin(annotation) is ClassVar:
            continue
        fields.append({"name": name, "type": format_annotation(annotation), "required": True})
        seen.add(name)

    try:
        signature = inspect.signature(error_type.__init__)
        init_hints = get_type_hints(error_type.__init__)
    except (NameError, TypeError, ValueError):
        return fields
    for parameter in signature.parameters.values():
        if parameter.name in {"self", "args", "kwargs"} or parameter.name in seen:
            continue
        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue
        annotation = init_hints.get(parameter.name, parameter.annotation)
        if annotation is inspect.Signature.empty:
            continue
        fields.append(
            {
                "name": parameter.name,
                "type": format_annotation(annotation),
                "required": parameter.default is inspect.Signature.empty,
            }
        )
        seen.add(parameter.name)
    return fields


def collect_models(*roots: type[Model]) -> tuple[type[Model], ...]:
    """Collect root and nested Model classes in dependency order."""
    seen: set[type[Model]] = set()
    ordered: list[type[Model]] = []

    def visit(model_type: type[Model]) -> None:
        if model_type in seen:
            return
        seen.add(model_type)
        for field in model_type.model_fields.values():
            for nested in model_types_from_annotation(field.annotation):
                visit(nested)
        ordered.append(model_type)

    for root in roots:
        visit(root)
    return tuple(ordered)


def model_types_from_annotation(annotation: object) -> tuple[type[Model], ...]:
    """Return nested Model classes referenced by an annotation."""
    if inspect.isclass(annotation) and issubclass(annotation, Model):
        return (annotation,)
    origin = get_origin(annotation)
    if origin is None:
        return ()
    found: list[type[Model]] = []
    for arg in get_args(annotation):
        found.extend(model_types_from_annotation(arg))
    return tuple(found)


def collect_errors(contract: Any) -> tuple[type[UseCaseError], ...]:
    """Collect declared and known error classes without duplicates."""
    seen: set[type[UseCaseError]] = set()
    ordered: list[type[UseCaseError]] = []
    for error_type in (*contract.raises, *contract.known_errors):
        if error_type not in seen:
            seen.add(error_type)
            ordered.append(error_type)
    return tuple(ordered)


def format_annotation(annotation: object) -> str:
    """Render an annotation as a Manifest type expression."""
    if annotation is None or annotation is type(None):
        return "None"
    if annotation is Any:
        return "Any"
    if inspect.isclass(annotation):
        return annotation.__name__
    origin = get_origin(annotation)
    return format_origin_annotation(origin, annotation)


def format_origin_annotation(origin: object, annotation: object) -> str:
    """Render a parametrized or union annotation."""
    if origin is Literal:
        values = ", ".join(repr(arg) for arg in get_args(annotation))
        return f"Literal[{values}]"
    if origin is Union or origin is types.UnionType:
        return " | ".join(format_annotation(arg) for arg in get_args(annotation))
    if origin in (list, dict, set, tuple):
        return format_collection_annotation(origin, get_args(annotation))
    return str(annotation).replace("typing.", "")


def format_collection_annotation(origin: object, args: tuple[object, ...]) -> str:
    """Render built-in collection annotations."""
    if origin is list and args:
        return f"list[{format_annotation(args[0])}]"
    if origin is set and args:
        return f"set[{format_annotation(args[0])}]"
    if origin is dict and len(args) == 2:
        return f"dict[{format_annotation(args[0])}, {format_annotation(args[1])}]"
    if origin is tuple and args:
        return "tuple[" + ", ".join(format_annotation(arg) for arg in args) + "]"
    return str(origin).replace("typing.", "")


__all__ = [name for name in globals() if not name.startswith("__")]
