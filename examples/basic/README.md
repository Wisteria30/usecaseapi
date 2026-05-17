# Basic example

This example demonstrates:

- contract and implementation modules under `src/commerce/usecases/.../v1/`;
- a single `commerce` package that owns the related usecases;
- explicit composition in `src/composition.py`;
- a workflow-like usecase that calls another usecase through `Caller`;
- declared dependency edges using `uses=`;
- a generated Manifest catalog in `usecaseapi.yaml`.

Regenerate the Manifest from the composed API:

```bash
PYTHONPATH=src uv run usecaseapi manifest export composition:usecases --output usecaseapi.yaml
```

## Swagger Preview

Run the local Swagger preview from this directory:

```bash
uv run usecaseapi swagger
```

Open `http://127.0.0.1:8000/docs` and use Swagger UI Try it out to call the example usecases.
If port `8000` is already in use, the command prints the next available preview URL.
Use `--port` to choose the starting port:

```bash
uv run usecaseapi swagger --port 8765
```

This example keeps its preview-only context fixture in `tests/usecaseapi_preview.py`.
The preview command discovers that file automatically, so the application root is not
polluted with preview-specific files.

The `x-usecaseapi-scenario` request header switches the inventory fixture used by the
preview context:

- `default`: `sku_456` has 10 units and `sku_sold_out` has 0 units.
- `empty`: both `sku_456` and `sku_sold_out` have 0 units.
- `rich`: `sku_456` has 100 units and `sku_sold_out` has 5 units.

Unknown scenario values fail explicitly instead of using another fixture.
