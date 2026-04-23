# Tasks: http-tools-layer

Tasks are grouped by phase. Within each phase, test tasks precede the
implementation tasks they verify. Implementation task dependencies
are declared explicitly.

## Phase 0: Dependencies + persona schema evolution

- [ ] 0.1 Add `pytest-httpserver>=1.0` to
  `[project.optional-dependencies.dev]` in `pyproject.toml` and run
  `uv sync --dev` so later phases' tests can import it.
  **Why early**: Phase 6 and Phase 8 tests import `pytest_httpserver`;
  adding it after those tasks run breaks TDD ordering.
  **Dependencies**: None.

- [ ] 0.2 Extend `src/assistant/core/persona.py:106-113` to accept a
  structured `auth_header` dict (`{type, env, header?}`) alongside the
  legacy flat `auth_header_env: VAR_NAME` form (auto-normalized to
  `{type: "bearer", env: VAR_NAME}`). Preserve backwards compatibility;
  update `PersonaConfig.tool_sources` type hint accordingly.
  **Design decisions**: D11.
  **Dependencies**: None.

- [ ] 0.3 Add tests for persona auth-header normalization at
  `tests/core/test_persona_auth_header.py`: structured dict form
  preserved as-is, legacy flat form normalized to bearer, absent
  `auth_header` returns `None`.
  **Dependencies**: 0.2.

- [ ] 0.4 Update the fixture personas under `tests/fixtures/personas/`
  to carry both a legacy `auth_header_env` source and a structured
  `auth_header` source so integration tests exercise both paths. Do
  NOT touch real persona submodules; only `tests/fixtures/personas/`.
  **Dependencies**: 0.2.

## Phase 1: Contracts + fixtures (verification only)

> The four OpenAPI fixtures below were authored during the plan phase
> and already exist in `openspec/changes/http-tools-layer/contracts/fixtures/`.
> The Phase 1 tasks verify their presence and shape — no new JSON is
> written here.

- [ ] 1.1 Verify `contracts/fixtures/sample_openapi_v3_1.json` exists,
  declares `openapi: "3.1.0"`, and contains three operations:
  `GET /items`, `GET /items/{id}`, `POST /items`. The POST operation
  uses `$ref: "#/components/schemas/ItemCreate"`.
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing (all),
  HTTP Tool Discovery (Successful discovery).
  **Dependencies**: None.

- [ ] 1.2 Verify `contracts/fixtures/sample_openapi_v3_0.json` exists
  and declares `openapi: "3.0.x"` for cross-version parsing coverage.
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing.
  **Dependencies**: None.

- [ ] 1.3 Verify `contracts/fixtures/malformed_openapi.json` is present
  and intentionally missing `paths` for the negative discovery test.
  **Spec scenarios**: http-tools — HTTP Tool Discovery (Source-level failure).
  **Dependencies**: None.

- [ ] 1.4 Verify `contracts/fixtures/sample_swagger_v2_0.json` exists
  with top-level `"swagger": "2.0"` for the 2.0-skip test.
  **Spec scenarios**: http-tools — HTTP Tool Discovery (Swagger 2.0 skip).
  **Dependencies**: None.

- [ ] 1.5 Validate the two 3.x fixtures (1.1, 1.2) with
  `openapi-spec-validator` to confirm they are spec-compliant and have
  not drifted. Skip fixtures 1.3 and 1.4 (intentionally non-conforming).
  **Dependencies**: 1.1, 1.2.

- [ ] 1.6 Add a cyclic-ref fixture at
  `contracts/fixtures/cyclic_ref_openapi.json` whose `components.schemas`
  contains `A → B → A` (two schemas each referencing the other).
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing (Cyclic $ref detected).
  **Dependencies**: None.

- [ ] 1.7 Add an external-ref fixture at
  `contracts/fixtures/external_ref_openapi.json` whose single operation's
  `requestBody.schema` is `{"$ref": "https://example.com/foo.json"}`.
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing (External $ref skipped).
  **Dependencies**: None.

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
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing
  (Operation with operationId, Operation without operationId).
  **Design decisions**: D5 (operationId slug fallback).
  **Dependencies**: 1.1, 1.2.

- [ ] 3.2 Implement `src/assistant/http_tools/openapi.py`: a minimal
  OpenAPI 3.x walker yielding `ParsedOperation(method, path,
  operation_id, parameters, request_body_schema, summary, description)`
  tuples from a loaded spec dict.
  **Dependencies**: 3.1.

- [ ] 3.3 Write tests for intra-document `$ref` resolution at
  `tests/http_tools/test_openapi.py::test_intra_ref_resolved` and
  `::test_intra_ref_nested_recursively`: against the 3.1 fixture
  (which uses `$ref: "#/components/schemas/ItemCreate"`), assert the
  ParsedOperation's `request_body_schema` has the inlined fields
  `name: str` and `quantity: int`. Against a synthetic nested fixture
  (built in-test), assert transitive resolution.
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing
  (Intra-document $ref resolved recursively).
  **Design decisions**: D10.
  **Dependencies**: 1.1, 3.2.

- [ ] 3.4 Write tests for external and cyclic `$ref` handling at
  `tests/http_tools/test_openapi.py::test_external_ref_skipped` and
  `::test_cyclic_ref_raises`: use fixtures 1.6 and 1.7; assert the
  external-ref operation is omitted (with `caplog` WARNING) and the
  cyclic-ref case raises `ValueError`.
  **Spec scenarios**: http-tools — OpenAPI Operation Parsing
  (External $ref skipped, Cyclic $ref detected).
  **Design decisions**: D10.
  **Dependencies**: 1.6, 1.7, 3.2.

- [ ] 3.5 Extend `src/assistant/http_tools/openapi.py`: add a
  `_resolve_ref(spec, ref_value, visited=None)` helper that walks
  JSON Pointer strings beginning with `#/`, detects cycles via the
  `visited` set, and raises `ValueError` on external refs (with an
  exception that the caller translates to a warning-and-skip).
  **Dependencies**: 3.3, 3.4.

## Phase 4: Tool builder

- [ ] 4.1 Write tests for `builder.py` at
  `tests/http_tools/test_builder.py`: builds StructuredTool for
  POST-with-body, GET-with-path-and-query, validates path parameter
  substitution, validates 5xx raises HTTPStatusError, validates
  description fallback (D6), validates args_schema is usable Pydantic.
  **Spec scenarios**: http-tools — Tool Builder Generates Typed
  StructuredTool (POST with JSON body, GET with path + query,
  Non-2xx response raises).
  **Design decisions**: D1 (runtime create_model), D2 (shared client),
  D6 (description fallback).
  **Dependencies**: 3.2.

- [ ] 4.2 Implement `src/assistant/http_tools/builder.py`: `_build_tool`
  factory + `_json_schema_to_pydantic` helper supporting
  string/integer/number/boolean/array/object types (recursive for
  nested objects) + path parameter substitution via
  `urllib.parse.quote` + format-string replacement.
  Sets `StructuredTool.name = f"{source_name}:{op_id}"`.
  **Dependencies**: 4.1.

- [ ] 4.3 Write tests for content-type + empty-body handling at
  `tests/http_tools/test_builder.py::test_non_json_content_type_raises`,
  `::test_204_returns_none`, and `::test_empty_body_returns_none`:
  stub httpx response objects with various Content-Type headers.
  **Spec scenarios**: http-tools — Tool Builder (Non-JSON 2xx raises,
  Empty-body 2xx returns None).
  **Dependencies**: 4.2.

- [ ] 4.4 Write tests for tool name and path-encoding at
  `tests/http_tools/test_builder.py::test_tool_name_matches_registry_key`
  and `::test_path_param_url_encoded`: assert
  `tool.name == "{source}:{op_id}"` and that invoking with
  `{"id": "foo/bar"}` produces a URL with `foo%2Fbar`.
  **Spec scenarios**: http-tools — Tool Builder (StructuredTool name
  matches registry key, Path parameter URL-encoded).
  **Dependencies**: 4.2.

- [ ] 4.5 Write tests for required/optional/default handling in
  `_json_schema_to_pydantic` at
  `tests/http_tools/test_builder.py::test_required_fields`,
  `::test_optional_field_uses_default`, and `::test_typeless_field_is_any`:
  build a schema with each case and assert the Pydantic model's
  `model_fields` metadata.
  **Spec scenarios**: http-tools — Tool Builder (Required JSON Schema
  fields produce required Pydantic fields).
  **Dependencies**: 4.2.

## Phase 5: Registry

- [ ] 5.1 Write tests for `registry.py` at
  `tests/http_tools/test_registry.py`: `list_all` returns tools in
  lexicographic key order (byte-identical across repeated calls),
  `by_source` filters, `by_preferred` filters by exact key match,
  empty registry returns `[]`.
  **Spec scenarios**: http-tools — HttpToolRegistry API (list_all
  returns every tool in key order, by_preferred filters by exact key
  match).
  **Design decisions**: D3 (`{source}:{op}` key format), D7 (concrete
  class, not Protocol).
  **Dependencies**: None.

- [ ] 5.2 Implement `src/assistant/http_tools/registry.py`:
  `HttpToolRegistry` class with `list_all` (lexicographic key sort),
  `by_source`, `by_preferred`; key-builder helper
  `tool_key(source, op_id)`.
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

- [ ] 6.4 Write integration tests for the HTTP client security posture
  at `tests/http_tools/test_discovery.py::test_redirect_refused`,
  `::test_oversized_response_skipped`, and
  `::test_timeout_skipped`: configure pytest-httpserver to return
  302 / 11MB body / 15s delay respectively and assert the source is
  skipped with a `caplog` WARNING. The WARNING record's message
  MUST NOT contain the auth-header value.
  **Spec scenarios**: http-tools — HTTP Client Security Posture (all).
  **Design decisions**: D9.
  **Dependencies**: 6.2.

- [ ] 6.5 Write integration test for missing auth env at
  `tests/http_tools/test_discovery.py::test_missing_auth_env_skipped`:
  configure a source whose `auth_header.env` names a variable that is
  unset; assert the source is skipped with a WARNING naming both the
  source and the missing variable, and that `discover_tools` does
  NOT raise.
  **Spec scenarios**: http-tools — HTTP Tool Discovery (Missing auth
  env var at discovery time).
  **Dependencies**: 6.2, 0.2.

- [ ] 6.6 Write integration test for credential redaction in logs at
  `tests/http_tools/test_discovery.py::test_auth_value_absent_from_logs`:
  trigger a discovery failure on a source with
  `auth_header: {type: bearer, env: TEST_TOKEN}` where
  `TEST_TOKEN=s3cr3t-t0k3n-DO-NOT-LEAK`; assert no `caplog` record's
  rendered message contains `s3cr3t-t0k3n-DO-NOT-LEAK` or `Bearer`.
  **Spec scenarios**: http-tools — HTTP Client Security Posture (Auth
  header value absent from logs).
  **Dependencies**: 6.2.

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

- [ ] 9.1 Confirm Phase 0.1 landed the `pytest-httpserver>=1.0` dev
  dependency and `uv sync --dev` produced a clean lockfile. No new
  deps expected at this point; if any leaf module pulled in an
  unexpected transitive, audit here.
  **Dependencies**: 0.1.

- [ ] 9.2 Add `openapi-spec-validator>=0.7` to
  `[project.optional-dependencies.dev]` if tasks 1.5 use it (they do —
  for fixture drift protection).
  **Dependencies**: 1.5.

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
