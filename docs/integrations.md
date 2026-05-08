# Integrations

UseCaseAPI is intentionally runtime-agnostic.

## FastAPI

```python
@app.post("/orders")
async def endpoint(input: Input, request: Request) -> Output:
    ctx = AppContext(session=request.state.session, actor=request.state.actor)
    return await usecases.caller(ctx).call(PLACE_ORDER, input)
```

FastAPI remains responsible for request lifecycle, dependency injection, authentication, and transaction setup.

## Django

```python
async def view(request: HttpRequest) -> JsonResponse:
    ctx = AppContext(request=request)
    output = await usecases.caller(ctx).call(PLACE_ORDER, input)
    return JsonResponse(output.model_dump())
```

Django middleware and transaction management remain outside UseCaseAPI.

## Workers and CLIs

Create a context at job or command start, then call usecases through the caller.

## AI agents

UseCaseAPI contracts can be exported as a catalog for an agent runtime. The catalog is documentation and selection metadata; it is not the source of truth.
