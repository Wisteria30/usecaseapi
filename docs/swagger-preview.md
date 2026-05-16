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
`api` or `usecases` object, creates local `POST` routes for bound usecases, and
serves Swagger UI at:

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

When `--preview` is not provided, the command searches in this order:

1. `tests/usecaseapi_preview.py`
2. `dev/usecaseapi_preview.py`
3. `src/composition.py`
4. `composition.py`
5. `usecaseapi_preview.py`
6. `preview.py`

Root-level preview files are supported for compatibility, but the recommended
project-owned preview location is `tests/usecaseapi_preview.py` or
`dev/usecaseapi_preview.py`.

You can also point the command at a specific preview module:

```bash
uv run usecaseapi swagger --preview usecaseapi_preview
uv run usecaseapi swagger --preview tests/usecaseapi_preview.py
uv run usecaseapi swagger --preview path/to/usecaseapi_preview.py
```
