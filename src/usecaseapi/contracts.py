"""Contract metadata and typed usecase references."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar, runtime_checkable

from .errors import ContractDefinitionError, UseCaseError
from .model import Model

InputT = TypeVar("InputT", bound=Model)
OutputT = TypeVar("OutputT", bound=Model)
UseCaseInputT = TypeVar("UseCaseInputT", bound=Model, contravariant=True)
UseCaseOutputT = TypeVar("UseCaseOutputT", bound=Model, covariant=True)


@runtime_checkable
class UseCase(Protocol[UseCaseInputT, UseCaseOutputT]):
    """Structural protocol for a same-process usecase implementation."""

    async def __call__(self, input: UseCaseInputT, /) -> UseCaseOutputT:
        """Run the usecase."""


@dataclass(frozen=True, slots=True)
class Contract[InputT: Model, OutputT: Model]:
    """Runtime metadata for a Protocol-first usecase contract."""

    name: str
    version: int
    input: type[InputT]
    output: type[OutputT]
    raises: tuple[type[UseCaseError], ...] = ()
    known_errors: tuple[type[UseCaseError], ...] = ()
    stable: bool = True
    deprecated: bool = False
    superseded_by: str | None = None
    description: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        """Validate contract metadata after dataclass initialization."""
        if not self.name or not self.name.strip():
            raise ContractDefinitionError("contract name must not be empty")
        if self.version < 1:
            raise ContractDefinitionError("contract version must be >= 1")
        if not issubclass(self.input, Model):
            raise ContractDefinitionError("contract input must inherit usecaseapi.Model")
        if not issubclass(self.output, Model):
            raise ContractDefinitionError("contract output must inherit usecaseapi.Model")
        for error_type in (*self.raises, *self.known_errors):
            if not issubclass(error_type, UseCaseError):
                raise ContractDefinitionError(
                    "contract errors must inherit usecaseapi.UseCaseError"
                )
        if self.raises:
            for error_type in self.known_errors:
                if not any(issubclass(error_type, declared) for declared in self.raises):
                    raise ContractDefinitionError(
                        f"known error {error_type.__qualname__} is not covered by raises"
                    )

    @property
    def key(self) -> str:
        """Stable contract key in ``name@vN`` form."""
        return f"{self.name}@v{self.version}"


@dataclass(frozen=True, slots=True)
class UseCaseRef[InputT: Model, OutputT: Model]:
    """Typed token used to call and bind a usecase contract."""

    protocol: type[Any]
    contract: Contract[InputT, OutputT]

    @property
    def key(self) -> str:
        """Stable contract key in ``name@vN`` form."""
        return self.contract.key

    @property
    def name(self) -> str:
        """Contract name without the version suffix."""
        return self.contract.name

    @property
    def version(self) -> int:
        """Contract major version."""
        return self.contract.version

    def __repr__(self) -> str:
        """Return a compact debug representation."""
        return f"UseCaseRef({self.key})"


def define_usecase[InputT: Model, OutputT: Model](
    protocol: type[Any],
    contract: Contract[InputT, OutputT],
) -> UseCaseRef[InputT, OutputT]:
    """Create a typed token for a usecase Protocol and its contract metadata."""
    if protocol is object:
        raise ContractDefinitionError("protocol must be a concrete Protocol class")
    return UseCaseRef(protocol=protocol, contract=contract)
