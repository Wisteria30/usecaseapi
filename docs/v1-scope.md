# V1 Scope

UseCaseAPI v1 is considered complete when it provides:

- Protocol-first contracts.
- Pydantic v2 input and output models.
- Real exception hierarchy for domain errors.
- Versioned `UseCaseRef` tokens.
- Same-process direct calls.
- Explicit binding to implementation factories.
- Host-owned context propagation.
- Declared usecase dependency graph.
- Strict undeclared-call detection.
- Declared-domain-error validation.
- `ExceptionGroup`-preserving concurrent call helper.
- Manifest YAML export, validation, diff, docs, graph, and scaffold CLI.
- Strict mypy-compatible typed implementation.
- Python 3.12, 3.13, and 3.14 CI.
- uv-based packaging and release workflow.

## Out of scope

UseCaseAPI v1 does not provide:

- DI container;
- transaction manager;
- database session lifecycle;
- HTTP server;
- RPC runtime;
- queue runtime;
- workflow persistence;
- retry engine;
- saga or outbox implementation;
- OpenAPI as source of truth;
- framework-specific monkeypatching;
- mypy plugin requirement.
