# Integrations

UseCaseAPI is intentionally runtime-agnostic.

## FastAPI

```python
@app.post("/commerce/place-order")
async def endpoint(input: Input, request: Request) -> Output:
    ctx = AppContext(session=request.state.session, actor=request.state.actor)
    return await usecases.caller(ctx).call(PLACE_ORDER_USECASE, input)
```

FastAPI remains responsible for request lifecycle, dependency injection, authentication, and transaction setup.

## Django

```python
async def view(request: HttpRequest) -> JsonResponse:
    ctx = AppContext(request=request)
    output = await usecases.caller(ctx).call(PLACE_ORDER_USECASE, input)
    return JsonResponse(output.model_dump())
```

Django middleware and transaction management remain outside UseCaseAPI.

## Workers and CLIs

Create a context at job or command start, then call usecases through the caller.

## AI agents

UseCaseAPI contracts can be exported as a catalog for an agent runtime. The catalog
is documentation and selection metadata; it is not the source of truth.

Use `manifest_from_api(api)` or `usecaseapi manifest export` to list contract names,
versions, input and output schemas, public error boundaries, known leaf errors, and
declared graph edges.
An agent adapter can map a selected tool back to a same-process
`caller.call(USECASE_REF, input)` call.

UseCaseAPI does not directly integrate with any LLM vendor.
