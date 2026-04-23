# Design: http-tools-layer

## Context

P1 shipped the `tool_sources` config schema in `persona.py`
(`{base_url, auth_header, allowed_tools}`) and the `DefaultToolPolicy`
in P1.8's `capability-protocols`. Neither has a consumer — the
discovery + tool-building layer has been `tools=[]` with a warning
since P1. This change implements that consumer, respecting the
user-confirmed decisions from the Gate 1 discovery questions:

- **OpenAPI 3.x** as the discovery wire format.
- **Extend `DefaultToolPolicy`** rather than introduce a new policy or
  tool-source abstraction.
- **pytest-httpserver** for integration tests.
- **Static bearer + api-key only** — OAuth / refresh deferred to P5 +
  P10.

## Goals

- Every operation advertised by a persona's configured service is
  available as a LangChain `StructuredTool` at agent startup.
- Per-role `preferred_tools` filtering works identically for HTTP tools
  and extension tools.
- Failure of one source does not block startup or discovery of other
  sources — the assistant still runs with the tools it could
  successfully load.
- `assistant --list-tools` is a real subcommand usable for debugging
  persona configuration without entering the REPL.

## Non-Goals

- **OAuth / refresh tokens** — deferred to P5 `ms-graph-extension` and
  P10 `extension-lifecycle`. Static bearer / api-key only in P3.
- **Retries / circuit breaking** — deferred to P9 `error-resilience`.
  A discovery 5xx skips the source with a warning; a per-invocation
  5xx raises.
- **MCP tool sources / A2A tool sources** — deferred to P17 / P6. If a
  `ToolSource` abstraction is warranted later, we refactor then.
- **Persona-level `allowed_tools` filtering** — the existing schema
  field is honored through the registry's `by_preferred` semantics at
  the role level; persona-level restrictions are a future concern.
- **Streaming responses** — P3 tool coroutines call `client.request`
  and return parsed JSON bodies; streaming is not in scope.

## Architectural Decisions

### D1: Runtime Pydantic model generation via `pydantic.create_model()`

**Choice**: Generate the tool's `args_schema` at runtime from the
operation's parameter + requestBody JSON schemas using
`pydantic.create_model(__name, **fields, __base__=BaseModel)`.

**Rejected**: Pre-generated Pydantic models via
`datamodel-code-generator` committed to the repo.

**Reason**: Personas can declare arbitrary `tool_sources` — a work
persona and personal persona point at different services. Pre-generated
models would require a build step per persona config, breaking the
"clone and run" flow. Runtime generation is slower (~ms per operation)
but pays that cost exactly once at startup, and the generated models
are indistinguishable from hand-written ones to LangChain's tool
dispatch.

**Consequence**: `args_schema.model_json_schema()` produces valid
JSON-Schema usable by the LLM; field types map via a small
`json_schema_to_python` helper covering `string`, `integer`, `number`,
`boolean`, `array`, `object` (and nested objects via recursive
`create_model`).

### D2: Single shared `httpx.AsyncClient` per process

**Choice**: One `httpx.AsyncClient` instance owned by the CLI's async
entry point as an `async with` context manager. All discovered tools
capture it by closure reference; lifecycle is scoped to the session.

**Rejected**:
- Per-tool or per-source clients (socket leaks, pool fragmentation).
- `weakref.finalize(client, asyncio.run_until_complete(client.aclose()))`
  — `aclose()` is a coroutine and weakref callbacks run synchronously
  outside the event loop, typically after the loop is closed. This
  pattern cannot work.

**Reason**: HTTPX reuses the underlying connection pool across hosts,
so a single client handles multi-source traffic efficiently. An
`async with` scope in `cli._run_repl` (and `cli._list_tools`) yields
deterministic shutdown without finalizer gymnastics.

**Client configuration** (see D9 for security posture):

```python
async with httpx.AsyncClient(
    timeout=httpx.Timeout(10.0, connect=5.0),
    follow_redirects=False,
    verify=True,
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
) as client:
    registry = await discover_tools(pc.tool_sources, client=client)
    # ... create_agent, enter REPL ...
```

**Consequence**: Tool coroutines close over the shared client. Tests
inject a test client via the `client=` parameter. No finalizer is
registered; shutdown is structural (the `async with` block).

### D9: HTTP client security posture

**Choice**: The shared `httpx.AsyncClient` defaults to conservative
posture for all discovery + tool invocations:

- **Timeouts**: `httpx.Timeout(10.0, connect=5.0)` sets per-operation
  limits — **read=10s, write=10s, pool=10s, connect=5s**. HTTPX does
  not natively enforce a wall-clock *total* budget; each operation can
  take up to its named limit independently. A slow trickling response
  could therefore exceed the sum if the server stalls between reads.
  The 10 MiB response cap (below) plus the per-read timeout keep
  worst-case wall-clock bounded in practice. A future phase may wrap
  `discover_tools()` in `asyncio.wait_for(..., 15.0)` for a hard total
  budget; P3 does not.
- **`follow_redirects=False`** — a 3xx from a configured service is
  treated as a failed request. Prevents silent credential forwarding
  across origins if a service redirects to an attacker-controlled host.
- **`verify=True`** — TLS verification is mandatory. No per-persona
  opt-out in P3.
- **Response size cap**: 10 MiB (10 × 2²⁰ = 10,485,760 bytes) per
  response, applied to both discovery documents and per-tool
  responses. Enforced by **streaming** the response body via
  `response.aiter_bytes(chunk_size=65_536)` with a running byte
  counter; as soon as the counter exceeds 10 MiB the stream is
  aborted and `ValueError("response exceeds 10MiB")` is raised.
  `response.content` is NOT called on unverified responses (it would
  buffer the entire body into memory before any size check could
  fire, defeating the defense). Discovery treats this as a
  source-skip; per-tool invocation propagates the error.

  Additionally, if `Content-Length` is present and exceeds 10 MiB, the
  request MAY be rejected pre-read; if it is absent or underreported,
  the streaming check is authoritative.
- **Credential redaction in logs**: Any warning log emitted by
  `discovery.py` or `builder.py` MUST log the source name and status
  code only — never the request URL query string, request body,
  response body, or `Authorization` / custom auth-header values.

**Rejected**: Permissive defaults (no timeout, `follow_redirects=True`,
no size cap). Matches most HTTP library defaults but leaves the
assistant vulnerable to slowloris, SSRF-via-redirect, and memory
exhaustion from a misbehaving or hostile service.

**Reason**: The assistant makes outbound HTTP calls with credentials on
behalf of the user. A permissive client is a direct attack surface —
particularly given personas can be configured by less-technical users.

**Consequence**: Integration tests against pytest-httpserver exercise
each posture (timeout firing, redirect refused, oversized response
rejected, credentials absent from logs). The spec declares a
dedicated "HTTP Client Security Posture" requirement; tasks 6.4 / 6.5
/ 6.6 cover the discovery-side scenarios and task 4.6 covers the
invocation-side propagation scenarios.

### D10: OpenAPI `$ref` resolution

**Choice**: `openapi.py` resolves intra-document JSON Pointer `$ref`
values (starting with `#/`) against the OpenAPI document's
`components.schemas` before yielding a `ParsedOperation`. External
`$ref` values (HTTP URLs or file paths) are **not** resolved — the
operation is skipped with a warning.

**Rejected**:
- Passing `$ref` strings through untouched. Pydantic
  `create_model` has no concept of `$ref`; the resulting schema would
  reject any LLM-provided input.
- Full external `$ref` resolution. Would require recursive HTTP
  fetches at discovery time, expanding the attack surface and
  complicating offline tests.

**Reason**: Every non-trivial OpenAPI document uses `$ref` for
`requestBody` and response schemas —
`openspec/changes/http-tools-layer/contracts/fixtures/sample_openapi_v3_1.json`
itself references `#/components/schemas/ItemCreate`. The parser
cannot be correct without intra-document resolution. External refs are
rare in the `/openapi.json` endpoint output and add risk without
P3-level demand.

**Consequence**: `openapi.py` exposes a small `_resolve_ref(spec,
ref)` helper that walks the JSON Pointer. Cyclic refs are detected
via a visited-set and raise `ValueError`, surfaced to `discover_tools`
as a source-level skip. Spec scenarios under
"OpenAPI Operation Parsing" and "HTTP Tool Discovery" cover intra- and
external-ref cases.

### D11: Persona `auth_header` schema evolution

**Choice**: Extend `src/assistant/core/persona.py` to accept the
structured `auth_header` dict (`{type, env, header?}`) described in
the spec while preserving the existing flat `auth_header_env` shortcut
for backwards compatibility.

**Before**:

```yaml
tool_sources:
  backend:
    base_url_env: BACKEND_URL
    auth_header_env: BACKEND_TOKEN    # legacy: assumed bearer, env-resolved to string
```

**After** (structured form — P3 adds this):

```yaml
tool_sources:
  backend:
    base_url_env: BACKEND_URL
    auth_header:
      type: bearer
      env: BACKEND_TOKEN
  analyzer:
    base_url_env: ANALYZER_URL
    auth_header:
      type: api-key
      env: ANALYZER_KEY
      header: X-API-Key
```

**Legacy form still works**: Personas that keep `auth_header_env:
BACKEND_TOKEN` are auto-normalized to `{type: bearer, env:
BACKEND_TOKEN}` when loaded.

**Rejected**:
- Only supporting the structured form — breaks every existing persona
  fixture.
- Only supporting the flat form — cannot express `api-key` or custom
  header names, which are in the spec and confirmed at Gate 1.

**Reason**: `persona.py` currently resolves `auth_header_env` to a
flat string via `_env(...)` at load time. The spec's
`resolve_auth_header` receives a structured `AuthHeaderConfig` dict.
Without reconciliation, discovery would blow up on first real call.

**Consequence**: Phase 0 gains a task to extend `persona.py` +
`PersonaConfig` schema + fixtures. The existing `tool_sources` type
in `persona.py:106-113` changes shape (flat `auth_header: str` →
`auth_header: AuthHeaderConfig`). Tests under
`tests/fixtures/personas/` are updated to exercise both forms.

### D3: Registry key `"{source_name}:{operation_id}"`

**Choice**: Tool keys in the registry are `"backend:list_items"`,
`"analyzer:summarize"`, etc.

**Rejected**: Flat `operation_id` keys, or nested dict-of-dicts.

**Reason**: Different sources may advertise the same `operation_id`
(`list`, `search`, etc.). Flat namespacing collides. The prefix also
makes `role.preferred_tools` configurable at source granularity —
`preferred_tools: ["analyzer:*"]` is a natural future extension
(wildcard support) that a flat namespace can't support.

**Consequence**: `role.preferred_tools` for the `add-teacher-role`
change references `content_analyzer:search` and
`content_analyzer:knowledge_graph`. This is the key format the
registry produces, so those preferences resolve cleanly once the
content-analyzer service is configured as a `tool_source` named
`content_analyzer`.

### D4: Discovery failures skip the source, per-invocation failures raise

**Choice**: `discover_tools` catches per-source `httpx.HTTPError` and
`ValueError` (malformed OpenAPI), logs a warning, and omits that
source. Per-tool coroutines raise any HTTP error up the stack.

**Rejected**: Fail-fast on any discovery error.

**Reason**: A half-working assistant is more useful than a
non-starting one. If `gmail` discovery fails because a credential is
stale, the user should still have `calendar` and extension tools.
Per-invocation failures are different — the LLM decided to use a
tool, and silent fallback to "no result" would hide real errors.

**Consequence**: Log lines are the user's primary feedback for source
health; `--list-tools` promotes these to stdout and sets exit code 1.
P9 `error-resilience` will later wrap these in retry + circuit-break
logic; P3 does not attempt that.

### D5: OperationId fallback slug

**Choice**: When an OpenAPI operation has no `operationId`, synthesize
from method + path: `GET /items/{id}/history` →
`get_items_id_history`.

**Rejected**: Require `operationId` (raise on absence).

**Reason**: Many services auto-generate OpenAPI without stable
operation IDs. Requiring them pushes friction onto service authors.
The slug is deterministic so role `preferred_tools` referencing the
fallback name is stable across restarts.

### D6: Tool description from OpenAPI `summary` + `description`

**Choice**: `StructuredTool.description` = operation `summary`; if
empty, operation `description`; if both empty, synthesized default
`"HTTP {method} {path}"`.

**Reason**: The LLM relies on `description` for tool selection.
Services that annotate OpenAPI benefit; silent services still get a
minimally informative default.

### D7: `HttpToolRegistry` is a plain object (not Protocol)

**Choice**: Concrete class with `list_all`, `by_source`,
`by_preferred` methods. Not a runtime-checkable Protocol.

**Rejected**: `ToolSource` Protocol (see Approach B in proposal).

**Reason**: YAGNI. One concrete implementation; no second
implementer in sight for P3. P17 `mcp-server-exposure` can refactor
when it needs to.

### D8: Minimal `http_tools/__init__.py` — no eager re-exports of composite modules

**Choice**: `src/assistant/http_tools/__init__.py` re-exports only the
**leaf** module symbols (`resolve_auth_header`, `HttpToolRegistry`,
`AuthHeaderConfig`). Consumers import composite symbols
(`discover_tools`) directly from their module:
`from assistant.http_tools.discovery import discover_tools`.

**Rejected**: Eager re-export of the full public API from
`__init__.py`.

**Reason**: Under the coordinated-tier work-package DAG,
`wp-http-tools-leaves` lands before `wp-http-tools-composite`. If
`__init__.py` eagerly imports `from .discovery import discover_tools`,
the package would fail to import for every intermediate state between
the two merges. Minimal re-export keeps the package importable at every
point in the DAG. As a side benefit, explicit module imports produce
cleaner stack traces and make ownership (which package provides the
symbol) visible at the call site.

**Consequence**:
- `wp-http-tools-leaves` owns `__init__.py` exclusively; it is **not**
  modified by `wp-http-tools-composite` or later packages.
- `cli.py` and any tests import composite symbols via the explicit
  module path, never via the package root.
- If a future phase wants to promote `discover_tools` to the package
  root, it is additive and done in a single commit that post-dates
  both leaf and composite modules landing.

## Component Layout

```
src/assistant/http_tools/
├── __init__.py          # LEAF re-exports only: AuthHeaderConfig,
│                        #   resolve_auth_header, HttpToolRegistry (D8)
├── discovery.py         # discover_tools(), _fetch_openapi()
│                        #   — imported via full path, NOT from package root
├── openapi.py           # minimal OpenAPI 3.x walker (paths → operations)
│                        #   + intra-document $ref resolver (D10)
├── builder.py           # _build_tool(), _json_schema_to_pydantic()
├── auth.py              # resolve_auth_header(), AuthHeaderConfig
└── registry.py          # HttpToolRegistry, key naming helpers
```

Modifications:

```
src/assistant/core/capabilities/tools.py
  - DefaultToolPolicy.__init__ gains http_tool_registry param
  - authorized_tools merges registry
  - export_tool_manifest adds "http_tools" key

src/assistant/core/capabilities/resolver.py
  - CapabilityResolver.__init__ gains http_tool_registry param
  - Passed through to DefaultToolPolicy in both SDK and host paths

src/assistant/cli.py
  - Remove "deferred to P2" warning block
  - Call discover_tools before create_agent
  - Add --list-tools flag with short-circuit behavior
  - Pass registry to CapabilityResolver
```

Tests:

```
tests/http_tools/
├── __init__.py
├── conftest.py              # pytest-httpserver fixtures + sample OpenAPI
├── test_discovery.py        # incl. security posture + missing-env
├── test_openapi.py          # incl. $ref resolution (intra/external/cyclic)
├── test_builder.py          # incl. content-type, name, URL-encode, sec
├── test_auth.py
└── test_registry.py

tests/test_cli.py             # CLI discovery + --list-tools end-to-end
                              # (CliRunner + pytest-httpserver)
```

## Dependencies

Add to `pyproject.toml [project.optional-dependencies.dev]`:

```toml
pytest-httpserver = ">=1.0"
```

No new runtime dependencies: `httpx`, `pydantic`, `langchain-core`
already present.

## Testing Strategy

- **Unit**: `openapi.py`, `auth.py`, `registry.py`, `builder.py`
  tested against in-memory fixtures (no network).
- **Integration**: `tests/http_tools/test_discovery.py` and
  `tests/test_cli.py` use pytest-httpserver — a real HTTP server on a
  random port with `expect_request().respond_with_json(...)`. This
  exercises the full httpx call path including DNS/socket resolution.
- **Spec coverage**: Every `#### Scenario:` in the spec deltas MUST be
  covered by at least one test. Task list cross-references scenarios
  to test tasks.

## Risks

| Risk | Mitigation |
|------|-----------|
| OpenAPI variants (Swagger 2.0, OpenAPI 3.0 vs 3.1) differ subtly | Document explicit 3.x support; fail with warning on 2.0; test against both 3.0 and 3.1 fixtures |
| Async `httpx.AsyncClient` lifecycle leaks if CLI crashes | Scope the client to an `async with` block inside `_run_repl` and `_list_tools`; exceptions unwind through the context manager and release sockets deterministically |
| Service returns 3xx redirect to an attacker-controlled host, leaking credentials | `follow_redirects=False` (D9). A redirect is treated as a failed request at discovery time and propagated as an HTTPStatusError at invocation time |
| Service returns a multi-gigabyte OpenAPI document (intentionally or by mistake) | 10 MiB response-size cap (D9). Source is skipped with a warning; other sources and the CLI remain operational |
| Service returns an OpenAPI document with a cyclic `$ref` chain | `_resolve_ref` detects via visited-set and raises `ValueError`; discovery skips the source with a warning (D10) |
| Runtime `create_model` produces pickle-unfriendly models | We never pickle these; LangChain uses `model_json_schema()` which works on dynamic models. Documented in D1. |
| Service returns huge OpenAPI (1000+ operations) | Registry and filtering handle it; no perf target set for P3. If this becomes an issue, add a `max_operations_per_source` config field in a future phase. |
| Path parameter substitution breaks on regex-unsafe names | Use simple `{name}` format-string replacement; OpenAPI spec forbids nested braces, so this is safe |

## Open Questions

None blocking. A future phase may want:
- Wildcard `preferred_tools` matching (`"analyzer:*"`).
- Tool result schema awareness (currently tools just return parsed
  JSON; an output `args_schema` equivalent would help the LLM).
- Rate limiting / quota awareness per source.
