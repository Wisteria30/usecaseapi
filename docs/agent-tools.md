# AI Agent Tool Catalogs

UseCaseAPI can describe internal tools without turning them into HTTP endpoints.

Use `snapshot_from_api(api)` to list:

- contract name and version;
- input and output model schema;
- public error boundary;
- known leaf errors;
- declared graph edges.

This is useful for agent runtimes that need a tool surface. The runtime can map selected tools back to same-process `caller.call(USECASE_REF, input)` calls.

UseCaseAPI does not directly integrate with any LLM vendor. It provides a stable contract catalog that an adapter can consume.
