# UseCaseAPI Contract Check Design

## Goal

UseCaseAPI should provide a simple CI guard for repositories that commit
`usecaseapi.yaml` as their canonical contract file.

The guard verifies three things:

1. The committed `usecaseapi.yaml` is a valid UseCaseAPI OpenAPI profile document.
2. The committed `usecaseapi.yaml` is synchronized with the project code target.
3. A pull request does not change or remove an existing usecase contract version.

The intended user rule is intentionally small:

- Commit `usecaseapi.yaml`.
- Keep `usecaseapi.yaml` synchronized with code.
- Do not change the same usecase name and version.
- Add a new version when the contract changes.

## Non-Goals

This feature does not start the Swagger preview server and does not inspect
Swagger UI behavior.

Out of scope:

- FastAPI server startup.
- `/docs` or `/openapi.json` HTTP checks.
- OpenAPI Studio or Swagger UI browser checks.
- Fine-grained breaking versus non-breaking schema classification.
- Breaking-change allowlists.
- YAML config files for multiple checks.
- Automatic dependency installation.
- Release artifact baselines.

## GitHub Action Interface

The public action is a composite action:

```yaml
- uses: Wisteria30/usecaseapi/actions/contract-check@vX
  with:
    target: composition:usecases
    manifest: usecaseapi.yaml
```

Inputs:

- `target`: required Python import path for the `UseCaseAPI` instance.
- `manifest`: optional path to the committed contract file. Defaults to
  `usecaseapi.yaml`.

Multiple manifests are represented by multiple action steps. There is no config
file format.

```yaml
- uses: Wisteria30/usecaseapi/actions/contract-check@vX
  with:
    target: order.composition:usecases
    manifest: services/order/usecaseapi.yaml

- uses: Wisteria30/usecaseapi/actions/contract-check@vX
  with:
    target: payment.composition:usecases
    manifest: services/payment/usecaseapi.yaml
```

The action assumes checkout, Python setup, and dependency installation have
already happened in the caller workflow.

Example:

```yaml
permissions:
  contents: read
  issues: write
  pull-requests: write

steps:
  - uses: actions/checkout@v6
    with:
      fetch-depth: 0

  - uses: actions/setup-python@v6
    with:
      python-version: "3.13"

  - run: uv sync --frozen --extra dev

  - uses: Wisteria30/usecaseapi/actions/contract-check@vX
    with:
      target: composition:usecases
      manifest: usecaseapi.yaml
```

The action must not guess package managers, dependency extras, or import targets.
Missing dependencies or a bad target should fail explicitly.

## CLI Interface

The action should be a thin wrapper around CLI commands so the same behavior can
run locally or in other CI systems.

Add:

```bash
usecaseapi manifest guard base.yaml head.yaml
```

`guard` compares two committed manifest files and fails when:

- a usecase name and version that exists in `base.yaml` is missing from
  `head.yaml`;
- a usecase name and version exists in both files but its contract content
  changed.

`guard` succeeds when:

- `head.yaml` adds a new usecase name and version;
- `head.yaml` is identical to `base.yaml`.

Add a CI orchestration command:

```bash
usecaseapi manifest ci \
  --target composition:usecases \
  --manifest usecaseapi.yaml \
  --base-manifest /tmp/base/usecaseapi.yaml \
  --summary build/usecaseapi-contract-check/contract-check.md \
  --json build/usecaseapi-contract-check/contract-check.json
```

`manifest ci` should:

1. verify the head manifest exists;
2. validate the head manifest;
3. check code synchronization with `manifest check-sync`;
4. when `--base-manifest` is present, run the immutable-version guard;
5. write Markdown and JSON results;
6. exit non-zero when validation, synchronization, or guard checks fail.

For non-PR events, `--base-manifest` can be omitted. In that case the command
validates and checks synchronization only.

## Contract Identity And Immutability

Contract identity is the pair:

```text
usecase name + major version
```

This corresponds to the manifest operation metadata:

```yaml
x-usecaseapi:
  name: commerce.place_order
  version: 1
```

The implementation may use the existing `x-usecaseapi.key` value internally, but
user-facing messages should say `name@vN` or "usecase name and version" rather
than requiring users to understand an internal key term.

For each operation in `base.yaml`, find the operation in `head.yaml` with the
same usecase name and version.

- If no matching operation exists, report it as removed and fail.
- If the normalized operation content differs, report it as changed and fail.
- If new operations exist only in `head.yaml`, report them as additions and pass.

The guard does not classify schema changes. Any change to an existing usecase
name and version is a failure. This keeps the rule easy to understand and avoids
hidden policy branches.

## Normalization

Manifest comparison should use normalized semantic data rather than raw YAML
text. Formatting, YAML key order, comments, and equivalent JSON/YAML rendering
must not affect the result.

The comparison should be based on the loaded UseCaseAPI manifest model or on a
canonical dictionary derived from `load_manifest()`.

At minimum, the normalized comparison for an existing operation should include:

- OpenAPI operation fields used by UseCaseAPI: path, method, operationId,
  requestBody, responses, tags, summary, description, deprecated, examples.
- operation `x-usecaseapi` metadata.
- referenced component schemas used by the operation input, output, and domain
  error responses.
- root `x-usecaseapi.components.errors` entries referenced by the operation.

The first implementation can reuse the existing manifest diff machinery if it
already captures these semantics. If it does not, add a focused normalizer for
operation-level immutable comparison.

## PR Base Handling

On pull requests, the action should compare the PR head manifest with the same
manifest path from the PR base commit.

The composite action can do this by checking out the base commit into a temporary
directory, then passing that file to `manifest ci`.

Pseudo-flow:

```text
current workspace:
  head manifest = ${{ inputs.manifest }}

base workspace:
  checkout github.event.pull_request.base.sha
  base manifest = base-checkout/${{ inputs.manifest }}

run:
  usecaseapi manifest ci \
    --target "${{ inputs.target }}" \
    --manifest "${{ inputs.manifest }}" \
    --base-manifest "base-checkout/${{ inputs.manifest }}"
```

If the base manifest does not exist and the head manifest exists, treat all head
operations as additions and pass the guard. Validation and code synchronization
must still run on the head manifest.

If the head manifest does not exist, fail.

## Output

The CLI writes:

```text
build/usecaseapi-contract-check/head.usecaseapi.yaml
build/usecaseapi-contract-check/base.usecaseapi.yaml
build/usecaseapi-contract-check/contract-check.md
build/usecaseapi-contract-check/contract-check.json
```

The Markdown report should be concise:

```md
<!-- usecaseapi-contract-check -->

## UseCaseAPI Contract Check

Status: Failed

Manifest: `usecaseapi.yaml`
Target: `composition:usecases`

Failures:
- `commerce.place_order@v1` changed. Existing contract versions are immutable.
- `commerce.cancel_order@v1` was removed.

Additions:
- `commerce.place_order@v2`

Validation:
- Manifest: passed
- Code sync: passed
```

The JSON report should include enough structure for future automation:

```json
{
  "status": "failed",
  "manifest": "usecaseapi.yaml",
  "target": "composition:usecases",
  "validation": {
    "manifest": "passed",
    "sync": "passed"
  },
  "guard": {
    "removed": ["commerce.cancel_order@v1"],
    "changed": ["commerce.place_order@v1"],
    "added": ["commerce.place_order@v2"]
  }
}
```

## PR Comment

The action should post or update one PR comment using the marker:

```md
<!-- usecaseapi-contract-check -->
```

This follows the existing coverage PR comment pattern in this repository.

PR comment behavior:

- On pull requests, post or update the comment.
- On non-PR events, do not post a PR comment.
- If comment posting is attempted but GitHub permissions are missing, fail with a
  clear message instead of silently ignoring the problem.

The action should also append the Markdown report to `$GITHUB_STEP_SUMMARY`.

## Artifacts

The action should upload the `build/usecaseapi-contract-check/` directory as an
artifact.

Default artifact name:

```text
usecaseapi-contract-check
```

If multiple action steps are used in one workflow, users can override the
artifact name if the action exposes an optional `artifact-name` input. This input
is optional and does not affect validation behavior.

## Validation Evidence

The repository should validate this feature with:

- unit tests for immutable manifest guard behavior;
- unit tests for `manifest ci` output and exit behavior;
- unit tests for PR comment creation/update helper;
- a local example using `examples/basic/usecaseapi.yaml`;
- CI workflow usage in this repository against `examples/basic`.

Before completion, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv run coverage run -m pytest
uv run coverage report -m
```

The package coverage target remains 100%.
