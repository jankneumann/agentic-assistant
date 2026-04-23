# Tasks: http-tools-layer

Tasks are grouped by phase. Within each phase, test tasks precede the
implementation tasks they verify. Implementation task dependencies
are declared explicitly.

## Phase 1: Contracts + fixtures

- [ ] 1.1 Write sample OpenAPI 3.1 fixture at
  `openspec/changes/http-tools-layer/contracts/fixtures/sample_openapi_v3_1.json`
  with three operations: `GET /items`, `GET /items/{id}`, `POST /items`.
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing (both),
  HTTP Tool Discovery (Successful discovery).
  **Dependencies**: None.

- [ ] 1.2 Write sample OpenAPI 3.0 fixture at
  `openspec/changes/http-tools-layer/contracts/fixtures/sample_openapi_v3_0.json`
  to verify cross-version parsing.
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing.
  **Dependencies**: None.

- [ ] 1.3 Write malformed-OpenAPI fixture (missing `paths`) at
  `openspec/changes/http-tools-layer/contracts/fixtures/malformed_openapi.json`
  for negative discovery test.
  **Spec scenarios**: http-tools — HTTP Tool Discovery (Source-level failure).
  **Dependencies**: None.

- [ ] 1.4 Write Swagger 2.0 fixture at
  `openspec/changes/http-tools-layer/contracts/fixtures/sample_swagger_v2_0.json`
  (top-level `"swagger": "2.0"`) for the 2.0-skip test.
  **Spec scenarios**: http-tools — HTTP Tool Discovery (Swagger 2.0 document skipped).
  **Dependencies**: None.

- [ ] 1.5 Validate OpenAPI fixtures with `openapi-spec-validator` (or
  equivalent) to confirm they really are OpenAPI 3.x and not drifted.
  Applies only to the 3.x fixtures (1.1, 1.2), not 1.3 or 1.4 which
  are intentionally non-conforming.
  **Dependencies**: 1.1, 1.2.

## Phase 2: Package skeleton + auth

- [ ] 2.1 Write tests for `auth.py` at `tests/http_tools/test_auth.py`:
  bearer with env var, api-key with default header, api-key with
  custom header, missing env var raises KeyError.
  **Spec scenarios**: http-tools — Auth Header Resolution (all four).
  **Design decisions**: D1 (types limited to bearer/api-key).
  **Dependencies**: None.

- [ ] 2.2 Create `src/assistant/http_tools/__init__.py` re-exporting
  **only the leaf symbols** (`AuthHeaderConfig`, `resolve_auth_header`,
  `HttpToolRegistry`). Composite symbols (`discover_tools`) MUST NOT
  be imported here — see D8.
  **Design decisions**: D8 (minimal __init__ to preserve DAG import
  invariant).
  **Dependencies**: None.

- [ ] 2.3 Implement `src/assistant/http_tools/auth.py`:
  `AuthHeaderConfig` TypedDict + `resolve_auth_header` function per
  the scenarios in 2.1.
  **Dependencies**: 2.1, 2.2.

## Phase 3: OpenAPI parsing

- [ ] 3.1 Write tests for `openapi.py` at
  `tests/http_tools/test_openapi.py`: parses 3.1 + 3.0 fixtures,
  extracts operations with method/path/operationId/parameters/
  requestBody schema, synthesizes operationId fallback from method+path.
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing (both).
  **Design decisions**: D5 (operationId slug fallback).
  **Dependencies**: 1.1, 1.2.

- [ ] 3.2 Implement `src/assistant/http_tools/openapi.py`: a minimal
  OpenAPI 3.x walker yielding `ParsedOperation(method, path,
  operation_id, parameters, request_body_schema, summary, description)`
  tuples from a loaded spec dict.
  **Dependencies**: 3.1.

## Phase 4: Tool builder

- [ ] 4.1 Write tests for `builder.py` at
  `tests/http_tools/test_builder.py`: builds StructuredTool for
  POST-with-body, GET-with-path-and-query, validates path parameter
  substitution, validates 5xx raises HTTPStatusError, validates
  description fallback (D6), validates args_schema is usable Pydantic.
  **Spec scenarios**: http-tools — Tool Builder Generates Typed
  StructuredTool (all three).
  **Design decisions**: D1 (runtime create_model), D2 (shared client),
  D6 (description fallback).
  **Dependencies**: 3.2.

- [ ] 4.2 Implement `src/assistant/http_tools/builder.py`: `_build_tool`
  factory + `_json_schema_to_pydantic` helper supporting
  string/integer/number/boolean/array/object types (recursive for
  nested objects) + path parameter substitution via format-string.
  **Dependencies**: 4.1.

## Phase 5: Registry

- [ ] 5.1 Write tests for `registry.py` at
  `tests/http_tools/test_registry.py`: list_all returns deterministic
  order, by_source filters, by_preferred filters by exact key match,
  empty registry returns `[]`.
  **Spec scenarios**: http-tools — HttpToolRegistry API (both).
  **Design decisions**: D3 (`{source}:{op}` key format), D7 (concrete
  class, not Protocol).
  **Dependencies**: None.

- [ ] 5.2 Implement `src/assistant/http_tools/registry.py`:
  `HttpToolRegistry` class with `list_all`, `by_source`, `by_preferred`;
  key-builder helper `tool_key(source, op_id)`.
  **Dependencies**: 5.1.

## Phase 6: Discovery

- [ ] 6.1 Write integration tests for `discovery.py` at
  `tests/http_tools/test_discovery.py` using pytest-httpserver:
  successful discovery builds registry, `/openapi.json` 404 falls back
  to `/help`, source 5xx skipped with warning, invalid JSON skipped
  with warning, empty tool_sources returns empty registry. **Use the
  `caplog` fixture**: for each "skipped with warning" scenario, assert
  that `caplog.records` contains at least one record with
  `levelname == "WARNING"` and a `message` or `getMessage()` that
  includes the source name.
  **Spec scenarios**: http-tools — HTTP Tool Discovery (Successful
  discovery, openapi.json 404 fallback, Source-level failure, No
  tool_sources).
  **Design decisions**: D4 (skip on failure, log warning).
  **Dependencies**: 5.2, 4.2, 2.3.

- [ ] 6.2 Implement `src/assistant/http_tools/discovery.py`:
  `discover_tools(tool_sources)` async function orchestrating fetch
  + parse + build per source. Uses a single shared
  `httpx.AsyncClient` (D2) passed in or constructed internally.
  **Dependencies**: 6.1.

- [ ] 6.3 Write integration test for Swagger 2.0 skip at
  `tests/http_tools/test_discovery.py::test_swagger_2_0_skipped`:
  serve the 1.4 fixture from pytest-httpserver, assert the source is
  omitted from the returned registry, and assert a `caplog` WARNING
  record names the source and the string `"swagger"` or `"2.0"`.
  **Spec scenarios**: http-tools — HTTP Tool Discovery (Swagger 2.0
  document skipped with warning).
  **Dependencies**: 1.4, 6.2.

## Phase 7: Policy integration

- [ ] 7.1 Write tests for the `DefaultToolPolicy` extension at
  `tests/core/capabilities/test_tool_policy_http.py` (or extend
  `test_tool_policy.py`): http_tool_registry merged into
  authorized_tools, preferred_tools filters across both sources,
  None registry preserves prior behavior, export_tool_manifest
  includes `http_tools` key.
  **Spec scenarios**: tool-policy — DefaultToolPolicy Implementation
  (all three), Tool Manifest Export (both).
  **Dependencies**: 5.2.

- [ ] 7.2 Extend `src/assistant/core/capabilities/tools.py`:
  `DefaultToolPolicy.__init__` accepts `http_tool_registry`;
  `authorized_tools` merges + filters; `export_tool_manifest` adds
  `http_tools` key.
  **Dependencies**: 7.1.

- [ ] 7.3 Extend `src/assistant/core/capabilities/resolver.py`:
  `CapabilityResolver.__init__` accepts optional
  `http_tool_registry`; threaded through to the
  `DefaultToolPolicy` instantiation in both SDK and host paths.
  **Dependencies**: 7.2.

## Phase 8: CLI wiring

- [ ] 8.1 Write tests for CLI startup at
  `tests/test_cli.py::test_startup_discovers_http_tools` and
  `tests/test_cli.py::test_startup_skips_discovery_when_no_sources`:
  CliRunner + pytest-httpserver + monkeypatched persona fixture with
  `tool_sources`. Verify `discover_tools` is called (or not) per
  scenarios. Verify the "deferred to P2" warning no longer appears in
  stdout.
  **Spec scenarios**: http-tools — CLI Startup Integration (both).
  **Dependencies**: 7.3.

- [ ] 8.2 Write tests for `assistant --list-tools` at
  `tests/test_cli.py::test_list_tools_success`,
  `::test_list_tools_partial_failure`,
  `::test_list_tools_no_sources`: CliRunner + pytest-httpserver,
  asserting stdout content and exit codes.
  **Spec scenarios**: http-tools — `--list-tools` CLI Subcommand
  (all three), cli-interface — List Tools Prints Discovered HTTP
  Tools (all three), cli-interface — CLI Entry Point (List-tools
  flag short-circuits REPL).
  **Dependencies**: 7.3.

- [ ] 8.3 Modify `src/assistant/cli.py`: remove the "deferred to P2"
  warning block, call `await discover_tools(pc.tool_sources)` when
  any source has `base_url`, inject resulting registry into the
  capability chain, pass `registry.list_all()` as tools to
  `create_agent`.
  **Dependencies**: 8.1.

- [ ] 8.4 Modify `src/assistant/cli.py`: add `--list-tools` flag at
  the group level with short-circuit behavior per 8.2. Ensure
  mutually-exclusive with the default `run` subcommand.
  **Dependencies**: 8.2, 8.3.

## Phase 9: Dependencies + packaging

- [ ] 9.1 Add `pytest-httpserver>=1.0` to `pyproject.toml` under
  `[project.optional-dependencies.dev]`. Run `uv sync` to update the
  lockfile.
  **Dependencies**: None.

- [ ] 9.2 Add `openapi-spec-validator>=0.7` (dev only) if used in
  1.4, else skip.
  **Dependencies**: 1.4.

## Phase 10: Docs

- [ ] 10.1 Update `CLAUDE.md` "What's Not Yet Wired" section: remove
  the `http-tools-layer` entry.
  **Dependencies**: 8.4.

- [ ] 10.2 Update `openspec/roadmap.md` status table: flip P3
  `http-tools-layer` from `pending` to `in-progress` (already should
  be, since the change dir exists) — verify the markdown reflects
  reality.
  **Dependencies**: None.

## Phase 11: Integration + validation

- [ ] 11.1 Run `uv run pytest tests/` — full suite passes. No new
  test is skipped, no privacy-boundary guard tripped.
  **Dependencies**: all of Phase 2-8.

- [ ] 11.2 Run `uv run ruff check .` and `uv run ruff format --check .`
  — clean.
  **Dependencies**: all of Phase 2-8.

- [ ] 11.3 Run `openspec validate http-tools-layer --strict` — green.
  **Dependencies**: all spec files complete.

- [ ] 11.4 Manually exercise `assistant -p <fixture-persona> --list-tools`
  against a local pytest-httpserver-started OpenAPI service to
  smoke-test the happy path end-to-end outside the pytest context.
  **Dependencies**: 8.4.
