from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from usecaseapi import Contract, Model, UseCase, UseCaseAPI, UseCaseRef, define_usecase


class Input(Model):
    value: int


class Output(Model):
    value: int


class Increment(UseCase[Input, Output], Protocol):
    async def __call__(self, input: Input, /) -> Output: ...


INCREMENT: UseCaseRef[Input, Output] = define_usecase(
    Increment,
    Contract(name="verify.increment", version=1, input=Input, output=Output),
)


class IncrementImpl:
    async def __call__(self, input: Input, /) -> Output:
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
                "billing.capture_payment",
                "--contracts-root",
                str(root / "app" / "contracts"),
                "--implementations-root",
                str(root / "app" / "usecases"),
                "--tests-root",
                str(root / "tests"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert (root / "app" / "contracts" / "billing" / "capture_payment" / "v1.py").exists()
        assert (root / "app" / "usecases" / "billing" / "capture_payment.py").exists()
        assert (root / "tests" / "test_billing_capture_payment_v1.py").exists()


def main() -> int:
    asyncio.run(_verify_runtime())
    _verify_cli_scaffold()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
