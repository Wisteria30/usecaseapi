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

The command discovers a preview module, loads its `api` object, creates local
`POST` routes for bound usecases, and serves Swagger UI at:

```text
http://127.0.0.1:8000/docs
```

This is not a production HTTP adapter. Use it for local verification of inputs,
outputs, dependency wiring, and domain errors before committing application
contract changes.

## Preview Module

Create `usecaseapi_preview.py` at the project root:

```python
from __future__ import annotations

import sys

from pathlib import Path

from fastapi import Request

from usecaseapi.swagger import SwaggerPreviewError

_PROJECT_SRC = Path(__file__).resolve().parent / "src"
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

1. `usecaseapi_preview.py`
2. `preview.py`
3. `composition.py`
4. `src/composition.py`

You can also point the command at a specific preview module:

```bash
uv run usecaseapi swagger --preview usecaseapi_preview
uv run usecaseapi swagger --preview path/to/usecaseapi_preview.py
```
