# UseCaseAPI Swagger Preview Design

## Purpose

UseCaseAPI should provide a development-only preview server that lets maintainers and users
exercise bound usecases from a Swagger UI. The goal is quick manual verification of same-process
usecase contracts, inputs, outputs, dependency behavior, and domain errors. This feature is not a
production HTTP adapter and should not introduce production transport semantics into the core
runtime.

The intended user experience is:

```bash
uv run usecaseapi swagger
```

The command starts a local FastAPI application and prints the Swagger UI URL:

```text
UseCaseAPI Swagger preview running at:
  http://127.0.0.1:8000/docs
```

## Scope

This feature covers:

- discovering a local preview composition module by convention;
- loading a bound `UseCaseAPI` instance from that module;
- creating a FastAPI app with one `POST` route per bound usecase;
- exposing FastAPI Swagger UI for `Try it out`;
- parsing request bodies into the contract input Pydantic model;
- invoking the bound usecase through `api.caller(context).call(ref, input)`;
- serializing successful outputs as JSON;
- serializing `UseCaseError` instances as domain error envelopes;
- supporting request-specific preview context through a project-defined context factory.

This feature does not cover:

- production HTTP serving guarantees;
- authentication or authorization;
- CORS policy design;
- generated HTTP clients;
- persistent server lifecycle management;
- automatic database, dependency, or fixture discovery;
- mixing preview context into the usecase input schema.

## Preview Module Convention

The command should favor a zero-argument workflow. It should search for a preview module using a
small convention list, with `usecaseapi_preview.py` as the recommended entrypoint.

Initial discovery order:

1. `usecaseapi_preview.py`
2. `preview.py`
3. `composition.py`
4. `src/composition.py`

The preview module exports:

```python
api = usecases

def create_context():
    ...
```

`api` is required and must be a bound `UseCaseAPI` instance.

`create_context` is optional only when the preview can run with `None` context. If the project needs
runtime dependencies, the module must define `create_context`. The command must fail explicitly when
it cannot create a context; it must not invent fallback dependencies.

## Request-Specific Context

The context factory should support both simple and request-aware forms:

```python
def create_context() -> AppContext:
    ...
```

```python
async def create_context(request: Request) -> AppContext:
    ...
```

The request-aware form lets projects use headers or query parameters to switch scenarios without
changing the usecase input body:

```python
async def create_context(request: Request) -> AppContext:
    scenario = request.headers.get("x-usecaseapi-scenario", "default")
    stock_by_scenario = {
        "default": {"sku_456": 10, "sku_sold_out": 0},
        "empty": {"sku_456": 0, "sku_sold_out": 0},
    }
    return AppContext(store=InventoryStore(stock_by_scenario[scenario]))
```

UseCaseAPI should pass the FastAPI `Request` object to `create_context` when the factory accepts one
argument. Header names and query names remain project-defined. The library should not reserve or
inject a fixed context header in the first implementation.

## Request And Response Shape

The HTTP request body is always the usecase input model. Preview context is not mixed into the body.

Example request body:

```json
{
  "user_id": "user_123",
  "item": {
    "sku_id": "sku_456",
    "quantity": 2
  }
}
```

Successful responses use the output model JSON representation:

```json
{
  "order_id": "ord_123",
  "status": "accepted"
}
```

Domain errors use an envelope:

```json
{
  "code": "commerce.place_order.inventory_shortage",
  "error": "InventoryShortage",
  "message": "commerce.place_order.inventory_shortage",
  "payload": {
    "sku_id": "sku_sold_out",
    "requested": 2,
    "available": 0
  }
}
```

The first implementation can return domain errors with a generic client-error status code such as
`400`. More detailed status mapping is out of scope for the development preview.

## FastAPI Integration

FastAPI and Uvicorn should not become core runtime requirements. The `swagger` command may be
available in the CLI, but it should import FastAPI/Uvicorn lazily and produce an explicit install
error if preview dependencies are missing.

The recommended extra is:

```toml
[project.optional-dependencies]
swagger = [
  "fastapi>=0.115",
  "uvicorn>=0.30",
]
```

The command remains:

```bash
uv run usecaseapi swagger
```

If dependencies are missing, the error should explain the installation step without attempting an
implicit fallback.

## OpenAPI Shape

The preview app should generate routes from bound `UseCaseAPI` contracts and may use FastAPI's
native OpenAPI generation in the first version. The route paths should match the manifest profile:

```text
/_usecases/{dotted_usecase_name}/v{major}/call
```

The request model should be the contract input model and the success response model should be the
contract output model. This preserves the most important Swagger `Try it out` behavior even before
the preview app fully reuses `usecaseapi.yaml` as its OpenAPI document.

## CLI Shape

Initial command:

```bash
usecaseapi swagger
```

Useful options:

```bash
usecaseapi swagger --host 127.0.0.1 --port 8000
usecaseapi swagger --preview usecaseapi_preview
```

`--preview` is optional and should accept a module name or file path. The default remains convention
discovery.

## Error Handling

The command should fail explicitly when:

- FastAPI/Uvicorn dependencies are not installed;
- no preview module can be found;
- the preview module does not export `api`;
- `api` is not a `UseCaseAPI`;
- context creation fails;
- a route is called for an unbound usecase.

Unsupported or ambiguous behavior should not be silently guessed.

## Testing

Tests should cover:

- preview module discovery;
- missing dependency error path using import monkeypatching;
- FastAPI app route creation from bound contracts;
- successful usecase call through a test client;
- `UseCaseError` envelope serialization;
- request-aware `create_context(request)` scenario switching;
- CLI behavior for the no-argument convention path.

The basic example should add `usecaseapi_preview.py` so contributors can run the preview locally.
