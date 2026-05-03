# http-tools Specification

## Purpose
TBD - created by archiving change http-tools-layer. Update Purpose after archive.
## Requirements
### Requirement: HTTP Tool Discovery

The system SHALL provide an async `discover_tools(tool_sources)`
function that, given a mapping of source name to tool source config,
fetches an OpenAPI 3.x document from each configured source and returns
an `HttpToolRegistry` containing one tool per OpenAPI operation.

Discovery SHALL attempt `GET {base_url}/openapi.json` first, then fall
back to `GET {base_url}/help` if the first request returns 404.

A failed discovery for any individual source SHALL log a warning and be
omitted from the registry; it SHALL NOT abort discovery of other
sources or raise from `discover_tools`.

#### Scenario: Successful discovery builds registry

- **WHEN** `tool_sources` contains `{"backend": {"base_url": "http://localhost:9000"}}`
- **AND** `GET http://localhost:9000/openapi.json` returns a valid
  OpenAPI 3.x document with two operations `list_items` and `create_item`
- **THEN** `discover_tools(tool_sources)` MUST return a registry with
  exactly two entries keyed `"backend:list_items"` and `"backend:create_item"`

#### Scenario: openapi.json 404 falls back to /help

- **WHEN** `GET {base_url}/openapi.json` returns HTTP 404
- **AND** `GET {base_url}/help` returns a valid OpenAPI 3.x document
- **THEN** the registry MUST include operations from the `/help`
  response

#### Scenario: Source-level failure skipped with warning

- **WHEN** one source's OpenAPI endpoint returns HTTP 500
- **AND** another source returns a valid OpenAPI document
- **THEN** a warning MUST be logged referencing the failing source
- **AND** the returned registry MUST contain only the tools from the
  successful source
- **AND** `discover_tools` MUST NOT raise

#### Scenario: No tool_sources is a no-op

- **WHEN** `discover_tools({})` is called
- **THEN** an empty `HttpToolRegistry` MUST be returned

#### Scenario: Swagger 2.0 document skipped with warning

- **WHEN** a source returns a JSON document whose top-level key is
  `"swagger": "2.0"` (or is otherwise not an OpenAPI 3.x document)
- **THEN** a warning MUST be logged naming the source and the
  unsupported version
- **AND** the source MUST be omitted from the returned registry
- **AND** `discover_tools` MUST NOT raise

#### Scenario: Missing auth env var at discovery time skipped with warning

- **WHEN** a source's `auth_header` config references an environment
  variable that is not set in the process environment
- **THEN** `discover_tools` MUST catch the `KeyError` raised by
  `resolve_auth_header`
- **AND** MUST log a warning naming the source and the missing variable
  name
- **AND** MUST omit that source from the returned registry
- **AND** MUST NOT raise

### Requirement: OpenAPI Operation Parsing

The system SHALL parse each operation from the OpenAPI document and
extract `method`, `path`, `operationId`, `parameters` (path + query),
and `requestBody` schema. When an operation has no `operationId`, a
deterministic fallback SHALL be synthesized from the method and path
(lowercased, slash → underscore, non-alphanumeric stripped).

The system SHALL resolve intra-document JSON Pointer `$ref` values
(strings beginning with `#/`) against the OpenAPI document's
`components.schemas` before producing a Pydantic args model. External
`$ref` values (any value not beginning with `#/`) SHALL cause the
containing operation to be skipped with a warning. Cyclic `$ref`
chains SHALL be detected via a visited-set and raise a
`ValueError` surfaced as a source-level skip.

#### Scenario: Operation with operationId

- **WHEN** the operation document declares `"operationId": "list_items"`
- **THEN** the registry entry MUST be keyed `"{source}:list_items"`

#### Scenario: Operation without operationId

- **WHEN** the operation is `GET /items/{id}/history` with no
  `operationId`
- **THEN** the registry entry MUST be keyed
  `"{source}:get_items_id_history"` (or an equivalent deterministic
  slug)

#### Scenario: Intra-document $ref resolved recursively

- **WHEN** an operation's `requestBody.content.application/json.schema`
  is `{"$ref": "#/components/schemas/ItemCreate"}`
- **AND** `components.schemas.ItemCreate` resolves to an object with
  fields `{name: str, quantity: int}`
- **THEN** the tool's `args_schema` MUST include fields `name` and
  `quantity` with the correct types
- **AND** nested `$ref` values inside the resolved schema MUST be
  resolved transitively

#### Scenario: External $ref skipped with warning

- **WHEN** an operation's schema contains a `$ref` whose value does
  not begin with `#/` (e.g. `https://example.com/schema.json` or
  `./other.json#/foo`)
- **THEN** the operation MUST be omitted from the registry
- **AND** a warning MUST be logged naming the source and the
  operation's method/path

#### Scenario: Cyclic $ref detected

- **WHEN** an operation's schema references a chain that loops back
  on itself (e.g. `A` → `B` → `A`)
- **THEN** `_resolve_ref` MUST raise `ValueError`
- **AND** `discover_tools` MUST catch the error and skip the source
  with a warning

### Requirement: Tool Builder Generates Typed StructuredTool

The system SHALL provide a `_build_tool(source_name, op_id, operation,
schemas, client, auth_headers)` factory that returns a LangChain
`StructuredTool` whose `args_schema` is a Pydantic `BaseModel` subclass
generated at runtime (via `pydantic.create_model`) from the
operation's parameters + request body schema.

The returned tool's `name` SHALL equal the registry key
`"{source_name}:{operation_id}"` — identical to the key under which
the tool is registered in `HttpToolRegistry`.

The returned tool's async `coroutine` SHALL invoke
`client.request(method, path, params=..., json=..., headers=auth_headers)`,
substituting path parameters from the Pydantic model into `{placeholder}`
path segments, and return the parsed JSON response body.

Path parameter values SHALL be URL-encoded via
`urllib.parse.quote(value, safe="")` before substitution into the path
template. The explicit `safe=""` argument is required — the library
default `safe="/"` leaves `/` un-encoded, which would allow a
path-parameter value like `"foo/bar"` to alter the request path
structure.

If the 2xx response's `Content-Type` header is not `application/json`
(or a JSON-compatible variant such as `application/problem+json`), the
tool's coroutine SHALL raise `ValueError` naming the source and
operation. Empty-body 2xx responses (HTTP 204 or `Content-Length: 0`)
SHALL return `None`.

Required JSON Schema fields SHALL produce required Pydantic fields.
Optional fields SHALL use the schema's declared `default` when
present, else `None`. Schemas with neither `type` nor `$ref` SHALL
produce `Any` typed fields.

#### Scenario: POST tool with JSON body

- **WHEN** `_build_tool` is called with a `POST /items` operation
  whose `requestBody` schema has fields `{name: str, quantity: int}`
- **AND** the returned tool is invoked with `{"name": "widget", "quantity": 3}`
- **THEN** an HTTP `POST` to `{base_url}/items` MUST be issued
- **AND** the request JSON body MUST be `{"name": "widget", "quantity": 3}`

#### Scenario: GET tool with path + query parameters

- **WHEN** `_build_tool` wraps a `GET /items/{id}` operation with a
  query parameter `verbose: bool`
- **AND** the returned tool is invoked with `{"id": "42", "verbose": true}`
- **THEN** an HTTP `GET` to `{base_url}/items/42?verbose=true` MUST be
  issued

#### Scenario: Non-2xx response raises

- **WHEN** the tool's HTTP call returns status 500
- **THEN** the tool's coroutine MUST raise `httpx.HTTPStatusError` (or
  a wrapping exception whose `__cause__` is an `HTTPStatusError`)

#### Scenario: Non-JSON 2xx content-type raises

- **WHEN** the tool's HTTP call returns status 200 with
  `Content-Type: text/html`
- **THEN** the tool's coroutine MUST raise `ValueError` naming the
  source and operation

#### Scenario: Empty-body 2xx returns None

- **WHEN** the tool's HTTP call returns status 204 (No Content)
- **THEN** the tool's coroutine MUST return `None`

#### Scenario: StructuredTool name matches registry key

- **WHEN** `_build_tool` wraps operation `list_items` from source
  `backend`
- **THEN** the returned tool's `name` attribute MUST equal
  `"backend:list_items"`

#### Scenario: Path parameter URL-encoded

- **WHEN** `_build_tool` wraps `GET /items/{id}`
- **AND** the tool is invoked with `{"id": "foo/bar"}`
- **THEN** the request URL MUST be `{base_url}/items/foo%2Fbar`

#### Scenario: Required JSON Schema field is required in Pydantic

- **WHEN** an operation's `requestBody` schema declares
  `{"required": ["name"], "properties": {"name": {"type": "string"}}}`
- **THEN** the generated Pydantic model's `name` field MUST be
  required (no default, model validation fails when absent)

#### Scenario: Optional JSON Schema field uses declared default

- **WHEN** an operation's schema declares a property
  `{"type": "integer", "default": 1}` that is NOT in `required`
- **THEN** the generated Pydantic model's field MUST have default
  value `1`
- **AND** when the schema declares no `default`, the Pydantic field
  default MUST be `None`

#### Scenario: Typeless JSON Schema field is Any

- **WHEN** an operation's schema declares a property with neither
  `type` nor `$ref`
- **THEN** the generated Pydantic field type MUST be `Any`

#### Scenario: Oversized response at invocation time raises

- **WHEN** a tool's HTTP call returns a 2xx body exceeding 10 MiB
- **THEN** the tool's coroutine MUST raise
  `ValueError("response exceeds 10MiB")`

#### Scenario: Redirect at invocation time raises

- **WHEN** a tool's HTTP call returns HTTP 302 with a `Location`
  header
- **THEN** the tool's coroutine MUST raise `httpx.HTTPStatusError`
- **AND** no request to the redirect target MUST be issued

#### Scenario: Timeout at invocation time raises

- **WHEN** a tool's HTTP call exceeds the configured 10-second
  read timeout
- **THEN** the tool's coroutine MUST raise `httpx.TimeoutException`
  (or a subclass thereof)

### Requirement: HTTP Client Security Posture

The system SHALL configure the shared `httpx.AsyncClient` used for
discovery and all per-tool invocations with the following posture:

- **Timeout**: `httpx.Timeout(10.0, connect=5.0)` — 10s total, 5s
  connect.
- **Redirects**: `follow_redirects=False`. Any 3xx response SHALL be
  treated as a failed request.
- **TLS verification**: `verify=True`. No per-persona override in P3.
- **Response size cap**: Responses SHALL be enforced to a 10 MiB
  limit (10,485,760 bytes) via **streaming** — `response.aiter_bytes`
  with a running byte counter that aborts the stream and raises
  `ValueError("response exceeds 10MiB")` as soon as the cap is
  exceeded. The system SHALL NOT read `response.content` on
  unverified responses (which would buffer the full body before any
  size check). Discovery treats cap violations as a source-skip;
  per-tool invocation propagates the error.

Warning logs emitted by `discovery.py` or `builder.py` SHALL NOT
include the request URL's query string, the request body, the
response body, the `Authorization` header value, or any configured
custom auth-header value. Source identification in logs SHALL be
limited to the source name, the HTTP method, the status code, and a
brief reason phrase.

#### Scenario: Discovery redirect refused

- **WHEN** `GET {base_url}/openapi.json` returns HTTP 302 with a
  `Location: http://attacker.example.com/fake.json` header
- **THEN** the source MUST be omitted from the registry
- **AND** a warning MUST be logged naming the source and HTTP status
- **AND** the 302 response body MUST NOT be parsed as OpenAPI
- **AND** no request to the redirect target MUST be issued

#### Scenario: Oversized discovery response skipped

- **WHEN** a source returns an OpenAPI document larger than 10 MiB
  (10 × 1024 × 1024 = 10,485,760 bytes)
- **THEN** the source MUST be omitted from the registry
- **AND** a warning MUST be logged naming the source

#### Scenario: Discovery timeout skipped with warning

- **WHEN** a source's `/openapi.json` endpoint does not respond
  within the configured 10-second read timeout
- **THEN** the source MUST be omitted from the registry
- **AND** a warning MUST be logged naming the source and indicating
  a timeout

#### Scenario: Auth header value absent from logs

- **WHEN** discovery fails for a source whose auth header contains
  `"Bearer s3cr3t-t0k3n"`
- **THEN** the emitted warning log record MUST NOT contain the
  substring `"s3cr3t-t0k3n"`
- **AND** the log record MUST NOT contain the substring `"Bearer"`

### Requirement: Auth Header Resolution

The system SHALL provide `resolve_auth_header(auth_header_config)` that
reads a persona's `auth_header` configuration and returns a dictionary
of HTTP headers to attach to every request to that source. Supported
`type` values are `"bearer"` and `"api-key"`.

The system SHALL accept `auth_header_config` in two forms:

1. **Structured dict** `{type, env, header?}` — the canonical shape
   from P3 onwards.
2. **Legacy flat string** — a persona's `auth_header_env` field that
   resolves to a plain bearer token. The system SHALL auto-normalize
   this to `{type: "bearer", env: <original env var name>}`.

Credentials SHALL be read from the environment variable named by
`env:` in the config. A missing environment variable SHALL raise
`KeyError` at resolution time (surfaced and handled by
`discover_tools` as a source-skip per the "Missing auth env var at
discovery time skipped with warning" scenario).

#### Scenario: Bearer token from environment

- **WHEN** `auth_header_config = {"type": "bearer", "env": "API_TOKEN"}`
- **AND** the environment variable `API_TOKEN` is set to `"t0k3n"`
- **THEN** `resolve_auth_header(...)` MUST return
  `{"Authorization": "Bearer t0k3n"}`

#### Scenario: API key with default header name

- **WHEN** `auth_header_config = {"type": "api-key", "env": "API_KEY"}`
- **AND** the environment variable `API_KEY` is set to `"abc"`
- **THEN** the returned headers MUST include `{"X-API-Key": "abc"}`

#### Scenario: API key with custom header name

- **WHEN** `auth_header_config = {"type": "api-key", "env": "API_KEY", "header": "X-Custom"}`
- **THEN** the returned headers MUST include `{"X-Custom": "abc"}`

#### Scenario: Missing env var raises KeyError

- **WHEN** `auth_header_config` references an env var that is not set
- **THEN** `resolve_auth_header` MUST raise `KeyError` naming the
  missing variable

### Requirement: HttpToolRegistry API

The system SHALL provide an `HttpToolRegistry` object keyed by
`"{source_name}:{operation_id}"` with methods `list_all()` returning
all tools, `by_source(name)` returning tools from a single source, and
`by_preferred(preferred_tools)` returning only those tools whose keys
are in the provided iterable.

`list_all()` SHALL return tools sorted lexicographically by their
registry key so repeated calls produce byte-identical output.

#### Scenario: list_all returns every tool in key order

- **WHEN** a registry contains `"backend:list_items"` and
  `"analyzer:summarize"`
- **THEN** `list_all()` MUST return a list of length 2
- **AND** the order MUST be `[analyzer:summarize, backend:list_items]`
  (lexicographic by key)

#### Scenario: by_preferred filters by exact key match

- **WHEN** `preferred_tools = ["analyzer:summarize"]`
- **AND** the registry contains `"backend:list_items"` and
  `"analyzer:summarize"`
- **THEN** `by_preferred(preferred_tools)` MUST return a list
  containing only the `analyzer:summarize` tool

### Requirement: CLI Startup Integration

The CLI startup path (`assistant run`) SHALL call
`await discover_tools(pc.tool_sources)` before creating the agent
whenever any configured source has a non-empty `base_url`, and SHALL
pass the resulting registry to `CapabilityResolver`.

When the persona has no `tool_sources` configured (or all entries lack
`base_url`), the CLI SHALL skip discovery entirely and pass an empty
registry.

The CLI SHALL NOT emit the pre-P3 warning `"HTTP tool discovery is
deferred to P2"` anywhere in its output.

#### Scenario: Startup with configured tool source

- **WHEN** the persona has `tool_sources: {"backend": {"base_url": "http://..."}}`
- **AND** `assistant -p <persona>` is executed
- **THEN** `discover_tools` MUST be called with the persona's
  `tool_sources` before the agent is created
- **AND** the resulting registry MUST be injected into the
  `CapabilityResolver`

#### Scenario: Startup with no tool sources skips discovery

- **WHEN** the persona has `tool_sources: {}`
- **THEN** `discover_tools` MUST NOT be called
- **AND** the agent MUST still be created successfully

### Requirement: `--list-tools` CLI Subcommand

The CLI SHALL accept a `--list-tools` flag that triggers discovery and
prints a per-source breakdown of registered tools (name, description,
input schema field names) then exits. The exit code SHALL be `0` when
all configured sources discover successfully and `1` when at least one
source fails.

#### Scenario: --list-tools with successful sources

- **WHEN** `assistant -p <persona> --list-tools` is executed
- **AND** all configured `tool_sources` return valid OpenAPI
- **THEN** stdout MUST contain one section per source with the tool
  names beneath
- **AND** the exit code MUST be 0

#### Scenario: --list-tools with one failing source

- **WHEN** one of the configured sources returns HTTP 500
- **THEN** the output MUST include a line indicating the failed source
  and the reason
- **AND** the exit code MUST be 1

#### Scenario: --list-tools with no tool_sources

- **WHEN** the persona has `tool_sources: {}`
- **AND** `assistant -p <persona> --list-tools` is executed
- **THEN** the output MUST include the line `"No tool_sources configured."`
- **AND** the exit code MUST be 0

### Requirement: HTTP Tool Invocations Emit Observability Span

The system SHALL wrap every HTTP tool constructed by `src/assistant/http_tools/builder.py` such that each invocation emits a `trace_tool_call` observability span with `tool_kind="http"`. The wrapping SHALL happen inside `_build_structured_tool` (or its successor in the builder) so the observability integration is transparent to `discover_tools` consumers.

The emitted call MUST include `tool_name` (the builder-assigned tool name, typically `<source>.<operationId>`), `tool_kind="http"`, `persona`, `role`, and `duration_ms`. When the underlying HTTPX call raises, the span MUST be emitted with `error=<exception type name>` before the exception propagates. The sanitization requirement (see `observability` capability, Requirement "Secret Sanitization") SHALL apply to every error message and metadata field before the span is emitted. That Requirement already covers `Bearer`, `Authorization: Basic`, `Authorization: Digest`, and `Cookie` patterns; this Requirement reiterates the cross-reference so implementers wrapping HTTP tools do not miss it.

#### Scenario: HTTP tool invocation emits trace_tool_call

- **WHEN** an HTTP-discovered tool `linear.listIssues` is invoked with persona `personal` and role `assistant`
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the emitted call's kwargs MUST include `tool_name="linear.listIssues"`, `tool_kind="http"`, `persona="personal"`, and `role="assistant"`

#### Scenario: HTTP error propagates with trace emitted

- **WHEN** the HTTP call raises `httpx.HTTPStatusError` with a 503 status
- **THEN** `trace_tool_call` MUST be called with `error="HTTPStatusError"`
- **AND** the exception MUST propagate to the caller

#### Scenario: Authorization header does not leak into span metadata

- **WHEN** an HTTP tool invocation raises with a message that contains `Authorization: Bearer eyJhbGciOi...`
- **THEN** the emitted span's `metadata` string representation MUST contain `Bearer REDACTED`
- **AND** MUST NOT contain any portion of the original JWT value

