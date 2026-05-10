"""Verify that a built distribution works after installation."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile

from pathlib import Path
from typing import Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseAPI, UseCaseRef, define_usecase


class Input(Model):
    """Input for the distribution verification usecase."""

    value: int


class Output(Model):
    """Output for the distribution verification usecase."""

    value: int


class Increment(UseCase[Input, Output], Protocol):
    """Protocol used to verify runtime calls."""

    async def __call__(self, input: Input, /) -> Output:
        """Increment the input value."""
        ...


INCREMENT: UseCaseRef[Input, Output] = define_usecase(
    Increment,
    Contract(name="verify.increment", version=1, input=Input, output=Output),
)


class IncrementImpl:
    """Implementation used by the distribution verification script."""

    async def __call__(self, input: Input, /) -> Output:
        """Increment the input value."""
        return Output(value=input.value + 1)


async def _verify_runtime() -> None:
    api = UseCaseAPI[None]()
    api.bind(INCREMENT, lambda caller: IncrementImpl())
    output = await api.caller(None).call(INCREMENT, Input(value=41))
    assert output == Output(value=42)


def _verify_cli_scaffold() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        subprocess.run(
            [
                "usecaseapi",
                "scaffold",
                "billing",
                "capture_payment",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        assert (
            root / "billing" / "usecases" / "capture_payment" / "v1" / "capture_payment_contract.py"
        ).exists()
        assert (
            root / "billing" / "usecases" / "capture_payment" / "v1" / "capture_payment_usecase.py"
        ).exists()
        assert (
            root
            / "tests"
            / "billing"
            / "usecases"
            / "capture_payment"
            / "v1"
            / "test_capture_payment.py"
        ).exists()


def main() -> int:
    """Run distribution verification checks."""
    asyncio.run(_verify_runtime())
    _verify_cli_scaffold()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
