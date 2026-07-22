# mcp-server Specification

## Purpose
TBD - created by archiving change mcp-server-exposure. Update Purpose after archive.
## Requirements
### Requirement: MCP Streamable HTTP Transport

The system SHALL expose an MCP (Model Context Protocol) server over
the streamable HTTP transport, mounted at `/mcp` on the existing
FastAPI serving app when `make_app(..., enable_mcp=True)` is used.
The transport SHALL be implemented with the official `mcp` Python SDK
(low-level `Server` + `StreamableHTTPSessionManager`) configured
stateless with JSON responses: every POST is self-contained, no MCP
transport session is required, and conversation continuity is carried
exclusively by the `context_id` tool argument. The surface SHALL be
absent (404) when the flag is off, and SHALL NOT alter the AG-UI or
A2A surfaces. Transport authentication is deferred to P25; the CLI's
loopback-default bind is the interim access control.

#### Scenario: tools/list served over the mount

- **WHEN** the app is built with `enable_mcp=True`
- **AND** a JSON-RPC `tools/list` request is POSTed to `/mcp`
- **THEN** the response MUST be a JSON-RPC success whose result lists
  the served tools with `name`, `description`, and `inputSchema`

#### Scenario: Mount absent by default

- **WHEN** the app is built without `enable_mcp`
- **THEN** POSTs to `/mcp` MUST return HTTP 404
- **AND** the AG-UI routes MUST behave exactly as before

#### Scenario: AG-UI co-hosting

- **WHEN** the app is built with `enable_mcp=True`
- **THEN** `GET /health` MUST still return HTTP 200

### Requirement: Served Tools Are ToolSpec Renderings

The MCP server's `tools/list` SHALL be a pure rendering of internal
`ToolSpec` instances through the MCP adapter
(`render_mcp_tools` — see the `tool-spec` capability): the listing
entry's `name`, `description`, and `inputSchema` MUST equal the
ToolSpec's fields with no translation layer. `tools/call` SHALL
validate arguments against the tool's `inputSchema` and dispatch to
the matching ToolSpec's async handler.

#### Scenario: Listing mirrors the ToolSpec fields

- **WHEN** a ToolSpec named `ask` with input schema S is served
- **AND** `tools/list` is requested
- **THEN** the listing MUST contain an entry with `name="ask"` and
  `inputSchema` equal to S

#### Scenario: Arguments violating the schema are rejected as tool errors

- **WHEN** `tools/call` is invoked for `ask` without the required
  `message` argument
- **THEN** the result MUST carry `isError=true`
- **AND** the error content MUST reference the failed validation

### Requirement: One ask Tool Per Enabled Role

The system SHALL serve one `ask_<role>` tool per role enabled for the
persona (role names sanitized to the MCP tool-name charset
`[A-Za-z0-9_-]`), plus a generic `ask` tool bound to the serving
role. Each tool SHALL accept a required `message` string and an
optional `context_id` string, and SHALL return structured content
containing the assistant's `response` and the `context_id` of the
session that produced it. The generic `ask` tool SHALL share the
serving role's session registry so a conversation started via `ask`
can be continued via `ask_<serving-role>` and vice versa. The
persona's own tool inventory SHALL NOT be re-exported over MCP.

#### Scenario: Tool per role plus generic ask

- **WHEN** the persona enables roles `coder` and `researcher` and the
  app serves role `coder`
- **AND** `tools/list` is requested
- **THEN** the listing MUST contain exactly `ask_coder`,
  `ask_researcher`, and `ask`

#### Scenario: Result carries response and context_id

- **WHEN** `tools/call` invokes `ask_coder` with
  `{"message": "hello"}`
- **THEN** the structured result MUST contain a string `response`
- **AND** a `context_id` equal to the backing session's `thread_id`

### Requirement: MCP Session Multiplexing

The system SHALL multiplex MCP tool calls over per-role session
registries (the harness-adapter Session Registry contract): a call
without `context_id` MUST create a fresh session (a new harness +
agent built through the same persona/role pipeline as the AG-UI and
A2A surfaces); a call with a known `context_id` MUST reuse that
session (serialized per-session so concurrent calls do not interleave
turns); a call with an unknown or expired `context_id` MUST be
rejected as a tool error rather than silently creating a session.
Each `ask_<role>` tool's sessions MUST be bound to that role.

#### Scenario: Fresh session per contextless call

- **WHEN** `ask` is called twice without `context_id`
- **THEN** two distinct sessions MUST be created
- **AND** the two results MUST carry distinct `context_id` values

#### Scenario: Known context continues the conversation

- **WHEN** `ask` is called with the `context_id` returned by a prior
  call
- **THEN** the same session MUST serve the second call
- **AND** no new session MUST be created

#### Scenario: Unknown context is rejected

- **WHEN** `ask` is called with `context_id="never-created"`
- **THEN** the result MUST carry `isError=true` naming the unknown
  context id
- **AND** no session MUST be created

#### Scenario: Role tools run role-bound sessions

- **WHEN** `ask_researcher` is called without `context_id`
- **THEN** the created session's harness MUST be constructed with the
  `researcher` role

### Requirement: MCP Error Mapping

The system SHALL map failures on the MCP surface to protocol-correct
shapes: an unknown tool name and any exception raised by a ToolSpec
handler MUST surface as a `tools/call` result with `isError=true`
(message text preserved), not as a transport failure; malformed
JSON-RPC envelopes are handled by the SDK transport layer.

#### Scenario: Unknown tool name

- **WHEN** `tools/call` is invoked with `name="nope"`
- **THEN** the result MUST carry `isError=true`
- **AND** the error content MUST name the unknown tool

