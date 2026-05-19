# Swagger Preview

UseCaseAPI includes a development-only Swagger preview for bound usecases.

Application users should install the optional Swagger dependencies:

```bash
uv add "usecaseapi[swagger]"
```

Repository contributors can install the preview dependencies with either command:

```bash
uv sync --extra swagger
uv sync --extra dev --extra swagger
```

```bash
uv run usecaseapi swagger
```

The command discovers an existing composition or preview module, loads its
`api` or `usecases` object, or calls a zero-argument `create_api()` or
`create_usecases()` factory. It creates local `POST` routes for bound usecases
and serves Swagger UI at:

```text
http://127.0.0.1:8000/docs
```

If the requested port is already in use, the command tries the next port until
it finds one it can bind. The selected URL is printed before the server starts:

```text
UseCaseAPI Swagger preview running at:
  requested port 8000 is unavailable; using 8001
  http://127.0.0.1:8001/docs
```

You can choose the starting port explicitly:

```bash
uv run usecaseapi swagger --port 8765
```

This is not a production HTTP adapter. Use it for local verification of inputs,
outputs, dependency wiring, and domain errors before committing application
contract changes.

## Composition First

For projects with an existing composition module, no preview-only file is
required. A normal composition module can export `usecases`:

```python
from usecaseapi import UseCaseAPI

usecases = UseCaseAPI[None]()
```

Then this command can start the preview without creating files in the project:

```bash
uv run usecaseapi swagger
```

The command also supports a zero-argument factory:

```python
from usecaseapi import UseCaseAPI


def create_usecases() -> UseCaseAPI[None]:
    usecases = UseCaseAPI[None]()
    return usecases
```

Use a preview module only when local verification needs request-specific
fixtures, headers, or test data that should not live in the application
composition.

## Preview Module

Create `tests/usecaseapi_preview.py` when the preview needs development-only
fixtures:

```python
from __future__ import annotations

import sys

from pathlib import Path

from fastapi import Request

from usecaseapi.swagger import SwaggerPreviewError

_PROJECT_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(_PROJECT_SRC))

from composition import AppContext, usecases  # noqa: E402


api = usecases


async def create_context(request: Request) -> AppContext:
    scenario = request.headers.get("x-preview-scenario")
    tenant_id = request.query_params.get("tenant_id", "local")

    if scenario is None:
        raise SwaggerPreviewError("missing required x-preview-scenario header")
    if scenario == "local":
        return AppContext(tenant_id=tenant_id)
    if scenario == "empty-inventory":
        return AppContext(tenant_id="empty-inventory")

    raise SwaggerPreviewError(f"unknown x-preview-scenario value: {scenario}")
```

The request body remains the usecase input. Use headers and query parameters
inside `create_context(request)` to switch local scenarios explicitly. This
example requires `x-preview-scenario` and rejects unknown values with
`SwaggerPreviewError` so the preview server returns visible text. The `tenant_id`
query parameter has a documented default of `local`. Preview modules should fail
visibly for missing or invalid scenario selection instead of using a silent
fallback.

## Discovery

When `--preview` is not provided, the command first checks explicit preview
files in this order:

1. `tests/usecaseapi_preview.py`
2. `dev/usecaseapi_preview.py`
3. `src/composition.py`
4. `composition.py`
5. `usecaseapi_preview.py`
6. `preview.py`

If none exist, it scans importable `composition.py` modules under `src/` and
the project root. Every discovered composition is loaded in memory. The command
builds a dependency graph from declared `uses`, collapses implementation-equivalent
subgraphs into their parent graph, and renders the remaining graphs in Swagger UI.

No files are generated in the application repository. The preview FastAPI app
exists only for the running command process.

You can point the command at one specific preview module or export:

```bash
uv run usecaseapi swagger --preview usecaseapi_preview
uv run usecaseapi swagger --preview app.composition:usecases
uv run usecaseapi swagger --preview app.composition:create_usecases
uv run usecaseapi swagger --preview tests/usecaseapi_preview.py
uv run usecaseapi swagger --preview path/to/usecaseapi_preview.py
```

## Multiple Compositions

When multiple compositions remain visible after graph resolution, preview routes
include the composition target to avoid OpenAPI path and operationId collisions:

```text
/_compositions/orders.composition/_usecases/orders.create_order/v1/call
/_compositions/payments.composition/_usecases/payments.authorize/v1/call
```

Swagger tags are assigned from dependency roots. If one root reaches a child
usecase through declared `uses`, the child operation receives the root tag too.
If a child is shared by two roots, the operation receives both tags.

Single-composition preview keeps the shorter route shape:

```text
/_usecases/orders.create_order/v1/call
```
