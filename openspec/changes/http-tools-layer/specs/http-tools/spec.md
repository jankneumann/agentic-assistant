# http-tools Specification Delta

## ADDED Requirements

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

### Requirement: OpenAPI Operation Parsing

The system SHALL parse each operation from the OpenAPI document and
extract `method`, `path`, `operationId`, `parameters` (path + query),
and `requestBody` schema. When an operation has no `operationId`, a
deterministic fallback SHALL be synthesized from the method and path
(lowercased, slash → underscore, non-alphanumeric stripped).

#### Scenario: Operation with operationId

- **WHEN** the operation document declares `"operationId": "list_items"`
- **THEN** the registry entry MUST be keyed `"{source}:list_items"`

#### Scenario: Operation without operationId

- **WHEN** the operation is `GET /items/{id}/history` with no
  `operationId`
- **THEN** the registry entry MUST be keyed
  `"{source}:get_items_id_history"` (or an equivalent deterministic
  slug)

### Requirement: Tool Builder Generates Typed StructuredTool

The system SHALL provide a `_build_tool(source_name, op_id, operation,
schemas, client, auth_headers)` factory that returns a LangChain
`StructuredTool` whose `args_schema` is a Pydantic `BaseModel` subclass
generated at runtime (via `pydantic.create_model`) from the
operation's parameters + request body schema.

The returned tool's async `coroutine` SHALL invoke
`client.request(method, path, params=..., json=..., headers=auth_headers)`,
substituting path parameters from the Pydantic model into `{placeholder}`
path segments, and return the parsed JSON response body.

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

### Requirement: Auth Header Resolution

The system SHALL provide `resolve_auth_header(auth_header_config)` that
reads a persona's `auth_header` configuration and returns a dictionary
of HTTP headers to attach to every request to that source. Supported
`type` values are `"bearer"` and `"api-key"`.

Credentials SHALL be read from the environment variable named by
`env:` in the config. A missing environment variable SHALL raise
`KeyError` at resolution time (surfaced during `discover_tools`).

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

#### Scenario: list_all returns every tool

- **WHEN** a registry contains `"backend:list_items"` and
  `"analyzer:summarize"`
- **THEN** `list_all()` MUST return a list of length 2 containing both
  tools in deterministic order

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
