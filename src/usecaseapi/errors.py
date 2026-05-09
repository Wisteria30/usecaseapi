"""Framework and domain error classes used by UseCaseAPI."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, ClassVar


class UseCaseAPIError(Exception):
    """Base class for framework-level errors raised by UseCaseAPI."""


class ContractDefinitionError(UseCaseAPIError):
    """Raised when a contract definition is invalid."""


class DuplicateUseCaseError(UseCaseAPIError):
    """Raised when the same usecase key is registered twice in an invalid way."""


class MissingBindingError(UseCaseAPIError):
    """Raised when a usecase is called without a registered implementation binding."""


class InvalidHandlerError(UseCaseAPIError):
    """Raised when a bound handler does not match its contract."""


class UndeclaredUseCaseDependencyError(UseCaseAPIError):
    """Raised when a usecase calls another usecase that was not declared in ``uses``."""

    def __init__(self, *, caller_key: str, callee_key: str) -> None:
        """Create an undeclared dependency error for a caller and callee pair."""
        self.caller_key = caller_key
        self.callee_key = callee_key
        super().__init__(f"{caller_key!r} attempted to call undeclared dependency {callee_key!r}")


class UndeclaredUseCaseError(UseCaseAPIError):
    """Raised when a handler leaks a domain error outside its declared raises contract."""

    def __init__(self, *, usecase_key: str, error: UseCaseError) -> None:
        """Create an undeclared domain error wrapper."""
        self.usecase_key = usecase_key
        self.error = error
        super().__init__(
            f"{usecase_key!r} raised undeclared usecase error "
            f"{type(error).__module__}.{type(error).__qualname__}"
        )


class UseCaseError(Exception):
    """Base class for domain errors that are part of a usecase contract.

    UseCaseAPI deliberately models domain failures as real Python exceptions.
    This preserves normal exception hierarchy behavior, stack traces, ``except`` /
    ``except*`` handling, and ExceptionGroup semantics.
    """

    code: ClassVar[str] = "usecase.error"

    @property
    def details(self) -> Mapping[str, Any]:
        """Public attributes attached to this domain exception."""
        return MappingProxyType(dict(self.__dict__))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation useful for docs, logs, or catalogs."""
        return {
            "type": f"{type(self).__module__}.{type(self).__qualname__}",
            "code": self.code,
            "message": str(self),
            "details": dict(self.details),
        }
