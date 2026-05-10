# Basic example

This example demonstrates:

- contract and implementation modules under `src/commerce/usecases/.../v1/`;
- a single `commerce` package that owns the related usecases;
- explicit composition in `src/composition.py`;
- a workflow-like usecase that calls another usecase through `Caller`;
- declared dependency edges using `uses=`.
