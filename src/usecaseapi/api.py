"""Runtime registry and caller implementation for UseCaseAPI contracts."""

from __future__ import annotations

import asyncio
import inspect

from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast, get_type_hints

from .contracts import InputT, OutputT, UseCase, UseCaseRef
from .errors import (
    DuplicateUseCaseError,
    InvalidHandlerError,
    MissingBindingError,
    UndeclaredUseCaseDependencyError,
    UndeclaredUseCaseError,
    UseCaseError,
)

ContextT = TypeVar("ContextT")

HandlerFactory = Callable[["Caller[Any]"], UseCase[Any, Any]]


@dataclass(frozen=True, slots=True)
class Binding[ContextT]:
    """A runtime connection between a contract token and an implementation factory."""

    ref: UseCaseRef[Any, Any]
    factory: Callable[[Caller[ContextT]], UseCase[Any, Any]]
    uses: frozenset[str] = field(default_factory=frozenset)
    description: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One edge observed during runtime calls."""

    caller_key: str | None
    callee_key: str


class UseCaseAPI[ContextT]:
    """Registry and contract runtime for same-process usecase calls.

    This class is not a DI container. It keeps contract bindings and creates
    ``Caller`` objects for contexts that are supplied by the host application.
    """

    def __init__(
        self,
        *,
        strict_dependencies: bool = True,
        strict_errors: bool = True,
        validate_handlers: bool = True,
    ) -> None:
        """Create a registry with dependency, error, and handler validation options."""
        self.strict_dependencies = strict_dependencies
        self.strict_errors = strict_errors
        self.validate_handlers = validate_handlers
        self._contracts: dict[str, UseCaseRef[Any, Any]] = {}
        self._bindings: dict[str, Binding[ContextT]] = {}
        self._handler_validator = HandlerValidator()
        self._error_policy = UseCaseErrorPolicy(strict=strict_errors)

    def register(self, *refs: UseCaseRef[Any, Any]) -> UseCaseAPI[ContextT]:
        """Register contracts without binding implementations yet."""
        for ref in refs:
            existing = self._contracts.get(ref.key)
            if existing is not None and existing is not ref:
                raise DuplicateUseCaseError(f"duplicate usecase contract {ref.key!r}")
            self._contracts[ref.key] = ref
        return self

    def bind(
        self,
        ref: UseCaseRef[InputT, OutputT],
        factory: Callable[[Caller[ContextT]], UseCase[InputT, OutputT]],
        *,
        uses: Iterable[UseCaseRef[Any, Any]] = (),
        replace: bool = False,
        description: str | None = None,
        tags: Sequence[str] = (),
    ) -> UseCaseAPI[ContextT]:
        """Bind a contract token to an implementation factory.

        ``factory`` receives the current ``Caller`` and returns a callable object
        that structurally conforms to the contract Protocol.
        """
        self.register(ref)
        if ref.key in self._bindings and not replace:
            raise DuplicateUseCaseError(f"duplicate binding for {ref.key!r}")
        use_keys = frozenset(use_ref.key for use_ref in uses)
        for use_ref in uses:
            self.register(use_ref)
        self._bindings[ref.key] = Binding(
            ref=ref,
            factory=cast(Callable[[Caller[ContextT]], UseCase[Any, Any]], factory),
            uses=use_keys,
            description=description,
            tags=tuple(tags),
        )
        return self

    def caller(self, context: ContextT) -> Caller[ContextT]:
        """Create a caller for a host-application context."""
        return Caller(api=self, context=context, current_key=None, records=[])

    def validate(self, *, require_handlers: bool = True) -> None:
        """Validate registry-level consistency.

        Handler signatures are validated lazily when a factory produces a handler,
        because UseCaseAPI deliberately does not own construction lifecycles.
        """
        if require_handlers:
            missing = sorted(set(self._contracts) - set(self._bindings))
            if missing:
                raise MissingBindingError("missing usecase bindings: " + ", ".join(missing))
        for binding in self._bindings.values():
            unknown_uses = sorted(binding.uses - set(self._contracts))
            if unknown_uses:
                raise MissingBindingError(
                    f"binding {binding.ref.key!r} declares unknown uses: " + ", ".join(unknown_uses)
                )

    @property
    def contracts(self) -> tuple[UseCaseRef[Any, Any], ...]:
        """Registered contract references in insertion order."""
        return tuple(self._contracts.values())

    @property
    def bindings(self) -> tuple[Binding[ContextT], ...]:
        """Registered implementation bindings in insertion order."""
        return tuple(self._bindings.values())

    def binding_for_ref(self, ref: UseCaseRef[Any, Any]) -> Binding[ContextT]:
        """Return the binding registered for a contract reference."""
        return self.binding_for_key(ref.key)

    def binding_for_key(self, key: str) -> Binding[ContextT]:
        """Return the binding registered for a usecase key."""
        binding = self._bindings.get(key)
        if binding is None:
            raise MissingBindingError(f"missing binding for {key!r}")
        return binding

    def validate_handler(self, ref: UseCaseRef[Any, Any], handler: UseCase[Any, Any]) -> None:
        """Validate a handler against the contract referenced by a usecase token."""
        self._handler_validator.validate(ref, handler)


class Caller[ContextT]:
    """Context-bound caller used to invoke usecase contracts."""

    def __init__(
        self,
        *,
        api: UseCaseAPI[ContextT],
        context: ContextT,
        current_key: str | None,
        records: list[CallRecord],
    ) -> None:
        """Create a context-bound caller used by the registry internals."""
        self._api = api
        self.context = context
        self._current_key = current_key
        self._records = records

    async def call(self, ref: UseCaseRef[InputT, OutputT], input: InputT, /) -> OutputT:
        """Call a usecase by contract token."""
        self.assert_declared_dependency(ref)
        binding = self._api.binding_for_ref(ref)
        self.validate_input(ref, input)
        self._records.append(CallRecord(caller_key=self._current_key, callee_key=ref.key))
        output = await self.invoke_binding(ref, binding, input)
        self.validate_output(ref, output)
        return cast(OutputT, output)

    async def gather(self, *awaitables: Awaitable[Any]) -> tuple[Any, ...]:
        """Run multiple usecase calls concurrently and preserve ExceptionGroup semantics."""
        results: list[Any] = [None] * len(awaitables)

        async def run_one(index: int, awaitable: Awaitable[Any]) -> None:
            results[index] = await awaitable

        async with asyncio.TaskGroup() as task_group:
            for index, awaitable in enumerate(awaitables):
                task_group.create_task(run_one(index, awaitable))
        return tuple(results)

    @property
    def records(self) -> tuple[CallRecord, ...]:
        """Runtime call records captured by this caller."""
        return tuple(self._records)

    def assert_declared_dependency(self, ref: UseCaseRef[Any, Any]) -> None:
        """Reject calls that are not declared by the current parent binding."""
        if self._current_key is None or not self._api.strict_dependencies:
            return
        parent = self._api.binding_for_key(self._current_key)
        if ref.key not in parent.uses:
            raise UndeclaredUseCaseDependencyError(
                caller_key=self._current_key,
                callee_key=ref.key,
            )

    def create_child_caller(self, ref: UseCaseRef[Any, Any]) -> Caller[ContextT]:
        """Create the caller context used inside a child usecase handler."""
        return Caller(
            api=self._api,
            context=self.context,
            current_key=ref.key,
            records=self._records,
        )

    async def invoke_binding(
        self,
        ref: UseCaseRef[InputT, OutputT],
        binding: Binding[ContextT],
        input: InputT,
    ) -> object:
        """Create, validate, and invoke the handler for one binding."""
        handler = binding.factory(self.create_child_caller(ref))
        if self._api.validate_handlers:
            self._api.validate_handler(ref, handler)

        try:
            result = handler(input)
            if not inspect.isawaitable(result):
                raise InvalidHandlerError(f"handler for {ref.key!r} did not return an awaitable")
            return await result
        except Exception as exc:
            self._api._error_policy.validate(ref, exc)
            raise

    def validate_input(self, ref: UseCaseRef[InputT, Any], input: object) -> None:
        """Validate that a call received the contract input model."""
        if isinstance(input, ref.contract.input):
            return
        raise InvalidHandlerError(
            f"input for {ref.key!r} was {type(input).__name__}, "
            f"expected {ref.contract.input.__name__}"
        )

    def validate_output(self, ref: UseCaseRef[Any, OutputT], output: object) -> None:
        """Validate that a handler returned the contract output model."""
        if isinstance(output, ref.contract.output):
            return
        raise InvalidHandlerError(
            f"handler for {ref.key!r} returned {type(output).__name__}, "
            f"expected {ref.contract.output.__name__}"
        )


class HandlerValidator:
    """Validate handler callable shape independently from the registry."""

    def validate(self, ref: UseCaseRef[Any, Any], handler: UseCase[Any, Any]) -> None:
        """Validate a handler against the referenced usecase contract."""
        target = callable_target(handler)
        self.validate_target(ref, target)

    def validate_target(self, ref: UseCaseRef[Any, Any], target: Callable[..., Any]) -> None:
        """Validate coroutine shape and annotations on a callable target."""
        if not inspect.iscoroutinefunction(target):
            raise InvalidHandlerError(f"handler for {ref.key!r} must be async")

        signature = inspect.signature(target)
        parameter = self.single_input_parameter(ref, signature)
        hints = get_type_hints(target)
        input_hint = hints.get(parameter.name, parameter.annotation)
        output_hint = hints.get("return", signature.return_annotation)
        self.validate_annotations(ref, input_hint=input_hint, output_hint=output_hint)

    def single_input_parameter(
        self,
        ref: UseCaseRef[Any, Any],
        signature: inspect.Signature,
    ) -> inspect.Parameter:
        """Return the single positional input parameter required by a handler."""
        positional_parameters = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if len(positional_parameters) != 1:
            raise InvalidHandlerError(
                f"handler for {ref.key!r} must accept exactly one positional input"
            )
        return positional_parameters[0]

    def validate_annotations(
        self,
        ref: UseCaseRef[Any, Any],
        *,
        input_hint: object,
        output_hint: object,
    ) -> None:
        """Validate handler input and return annotations against a contract."""
        if input_hint is inspect.Signature.empty:
            raise InvalidHandlerError(f"handler for {ref.key!r} must annotate input")
        if output_hint is inspect.Signature.empty:
            raise InvalidHandlerError(f"handler for {ref.key!r} must annotate return")
        if input_hint is not ref.contract.input:
            raise InvalidHandlerError(
                f"handler for {ref.key!r} input annotation must be "
                f"{ref.contract.input.__name__}, got {input_hint!r}"
            )
        if output_hint is not ref.contract.output:
            raise InvalidHandlerError(
                f"handler for {ref.key!r} return annotation must be "
                f"{ref.contract.output.__name__}, got {output_hint!r}"
            )


@dataclass(frozen=True, slots=True)
class UseCaseErrorPolicy:
    """Validate raised domain errors against a contract boundary."""

    strict: bool

    def validate(self, ref: UseCaseRef[Any, Any], exc: BaseException) -> None:
        """Reject undeclared UseCaseError instances when strict mode is enabled."""
        if not self.strict:
            return
        undeclared = find_undeclared_usecase_error(exc, ref.contract.raises)
        if undeclared is not None:
            raise UndeclaredUseCaseError(usecase_key=ref.key, error=undeclared) from exc


def callable_target(handler: UseCase[Any, Any]) -> Callable[..., Any]:
    """Return the callable object that should be inspected for a handler."""
    if inspect.isfunction(handler) or inspect.ismethod(handler):
        return cast(Callable[..., Any], handler)
    if not callable(handler):
        raise InvalidHandlerError(f"handler {handler!r} is not callable")
    return cast(Callable[..., Any], handler.__call__)


def find_undeclared_usecase_error(
    exc: BaseException,
    declared: tuple[type[UseCaseError], ...],
) -> UseCaseError | None:
    """Return the first domain error outside the declared contract boundary."""
    if isinstance(exc, UseCaseError):
        if declared and isinstance(exc, declared):
            return None
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for nested in exc.exceptions:
            found = find_undeclared_usecase_error(nested, declared)
            if found is not None:
                return found
    return None
