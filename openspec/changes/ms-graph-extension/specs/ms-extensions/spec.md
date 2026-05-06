## ADDED Requirements

### Requirement: ms_graph Extension Real Implementation

The system SHALL replace the `ms_graph` stub at
`src/assistant/extensions/ms_graph.py` with a real implementation that
exposes generic Microsoft Graph tools (people search, profile read,
cross-mailbox message search). The extension SHALL accept a
`GraphClient` instance at construction. Both `as_langchain_tools()`
and `as_ms_agent_tools()` SHALL return non-empty tool lists when the
persona enables this extension.

#### Scenario: as_langchain_tools returns non-empty list

- **WHEN** `create_extension(config={}, client=mock_client).as_langchain_tools()`
  is called
- **THEN** the returned list MUST contain at least three
  `StructuredTool` instances
- **AND** the tool names MUST include `ms_graph.search_people`,
  `ms_graph.get_my_profile`, `ms_graph.search_messages`

#### Scenario: as_ms_agent_tools returns non-empty list

- **WHEN** `create_extension(config={}, client=mock_client).as_ms_agent_tools()`
  is called
- **THEN** the returned list MUST contain at least three callables
- **AND** the callables MUST have names matching the LangChain tool
  names

#### Scenario: search_people calls /users with $search and returns parsed value list

- **WHEN** `await ext._search_people(query="alice")` is awaited
- **AND** the mock client's GET response for `/users` returns
  `{"value": [{"displayName": "Alice"}]}`
- **THEN** the tool's return value MUST be `[{"displayName": "Alice"}]`
- **AND** the GET request MUST include `$search="alice"` (URL-encoded)
  in `params`

#### Scenario: Default scopes include People.Read and User.Read

- **WHEN** `create_extension({})` is called with no scopes override
- **THEN** the resulting extension's `.scopes` MUST contain
  `"People.Read"` and `"User.Read"`

### Requirement: outlook Extension Real Implementation

The system SHALL replace the `outlook` stub at
`src/assistant/extensions/outlook.py` with a real implementation that
exposes Outlook mail and calendar read tools plus a `send_email`
write tool. The extension SHALL accept a `GraphClient` instance at
construction.

#### Scenario: Tool list includes read and write tools

- **WHEN** `create_extension({}, client=mock_client).as_langchain_tools()`
  is called
- **THEN** the returned list MUST include at least the tools
  `outlook.list_messages`, `outlook.read_message`,
  `outlook.search_messages`, `outlook.send_email`,
  `outlook.list_calendar_events`, `outlook.find_free_times`

#### Scenario: list_messages calls /me/messages and returns value array

- **WHEN** `await ext._list_messages(top=10)` is awaited
- **AND** the mock client returns
  `{"value": [{"id": "m1", "subject": "hi"}]}`
- **THEN** the tool MUST return `[{"id": "m1", "subject": "hi"}]`
- **AND** the GET request MUST include `$top=10` in params

#### Scenario: send_email POSTs to /me/sendMail with the expected body shape

- **WHEN** `await ext._send_email(to=["a@b.com"], subject="hi",
  body="hello")` is awaited
- **THEN** the mock client MUST receive a POST to `/me/sendMail`
- **AND** the JSON body MUST contain the keys
  `message.subject == "hi"`, `message.body.content == "hello"`,
  `message.toRecipients[0].emailAddress.address == "a@b.com"`

#### Scenario: Default scopes include Mail.Read, Mail.Send, and Calendars.Read

- **WHEN** `create_extension({})` is called with no scopes override
- **THEN** the resulting extension's `.scopes` MUST contain at least
  `"Mail.Read"`, `"Mail.Send"`, `"Calendars.Read"`

### Requirement: teams Extension Real Implementation

The system SHALL replace the `teams` stub at
`src/assistant/extensions/teams.py` with a real implementation that
exposes Teams chat and channel read tools plus a `post_chat_message`
write tool.

#### Scenario: Tool list includes read and write tools

- **WHEN** `create_extension({}, client=mock_client).as_langchain_tools()`
  is called
- **THEN** the returned list MUST include at least the tools
  `teams.list_chats`, `teams.list_channel_messages`,
  `teams.read_message`, `teams.post_chat_message`

#### Scenario: list_chats calls /me/chats and returns value array

- **WHEN** `await ext._list_chats()` is awaited
- **AND** the mock client returns `{"value": [{"id": "c1"}]}`
- **THEN** the tool MUST return `[{"id": "c1"}]`

#### Scenario: post_chat_message POSTs to /chats/{chatId}/messages

- **WHEN** `await ext._post_chat_message(chat_id="c1", text="hello")`
  is awaited
- **THEN** the mock client MUST receive a POST to
  `/chats/c1/messages`
- **AND** the JSON body MUST equal
  `{"body": {"content": "hello"}}`

#### Scenario: Default scopes include Chat.Read, Chat.ReadWrite, ChannelMessage.Read.All

- **WHEN** `create_extension({})` is called with no scopes override
- **THEN** the resulting extension's `.scopes` MUST contain at least
  `"Chat.Read"`, `"Chat.ReadWrite"`, `"ChannelMessage.Read.All"`

### Requirement: sharepoint Extension Real Implementation (Read-Only)

The system SHALL replace the `sharepoint` stub at
`src/assistant/extensions/sharepoint.py` with a real implementation
exposing SharePoint search and document read tools. SharePoint
write-side tools (list-item create, document upload) are explicitly
deferred to a P5b follow-up. The `download_document` tool SHALL use
the `CloudGraphClient.get_bytes()` method (50 MiB ceiling by default)
to retrieve binary content; the tool MUST return the result dict
structure `{"path", "size_bytes", "content_type", "request_id"}`
specified in the `graph-client` capability and MUST NOT return raw
bytes in memory.

#### Scenario: Tool list contains only read tools

- **WHEN** `create_extension({}, client=mock_client).as_langchain_tools()`
  is called
- **THEN** the returned list MUST include `sharepoint.search_sites`,
  `sharepoint.list_documents`, `sharepoint.download_document`
- **AND** no tool name MUST start with `sharepoint.create` or
  `sharepoint.upload`

#### Scenario: search_sites calls /sites with $search

- **WHEN** `await ext._search_sites(query="finance")` is awaited
- **THEN** the GET request MUST be to `/sites` with
  `$search="finance"` in params

#### Scenario: download_document delegates to get_bytes and returns metadata dict

- **WHEN** `await ext._download_document(item_id="abc")` is awaited
- **THEN** the tool MUST call `client.get_bytes(...)` with the
  endpoint `/me/drive/items/abc/content` (or equivalent SharePoint
  variant)
- **AND** the tool MUST return a dict with keys `path`, `size_bytes`,
  `content_type`, `request_id`
- **AND** the tool MUST NOT return raw `bytes` in its return value

#### Scenario: Default scopes include Sites.Read.All and Files.Read.All

- **WHEN** `create_extension({})` is called with no scopes override
- **THEN** the resulting extension's `.scopes` MUST contain at least
  `"Sites.Read.All"` and `"Files.Read.All"`

### Requirement: All Four Extensions Provide Real HealthStatus

The system SHALL ensure that `health_check()` on each of the four
real extensions returns a `HealthStatus` derived from the
extension-scoped circuit breaker via
`health_status_from_breaker(self._breaker, key=f"extension:{self.name}")`.
The previous stub return value (`HealthState.UNKNOWN` with
`reason="extension is a stub"`) SHALL no longer apply to these four
extensions.

#### Scenario: Real extension reports OK when breaker is CLOSED

- **WHEN** the breaker `extension:outlook` is CLOSED
- **AND** `await create_extension({}, client=mock_client).health_check()`
  is awaited
- **THEN** the returned `HealthStatus.state` MUST equal
  `HealthState.OK`
- **AND** `breaker_key` MUST equal `"extension:outlook"`

#### Scenario: Real extension reports UNAVAILABLE when breaker is OPEN

- **WHEN** the breaker `extension:teams` is OPEN
- **AND** `await create_extension({}, client=mock_client).health_check()`
  is awaited
- **THEN** the returned `HealthStatus.state` MUST equal
  `HealthState.UNAVAILABLE`

### Requirement: Tool Format Parity Between LangChain and MSAF

The system SHALL ensure that for each of the four real extensions,
`as_langchain_tools()` and `as_ms_agent_tools()` return lists of
equal length, and that for every index `i` the LangChain tool's
`.name` equals the MSAF tool's `__name__` (after `@ai_function`
decoration). This guarantees that swapping harnesses does not change
the tool surface a role can call.

#### Scenario: Tool counts match across formats

- **WHEN** `ext.as_langchain_tools()` returns `N` tools
- **AND** `ext.as_ms_agent_tools()` is called on the same instance
- **THEN** the second call MUST return exactly `N` tools

#### Scenario: Tool names match by index

- **WHEN** the LangChain list contains a tool with `name="outlook.list_messages"`
  at index `i`
- **AND** the MSAF list is collected from the same extension instance
- **THEN** the MSAF list's element at index `i` MUST have an
  `@ai_function`-recorded name equal to `"outlook.list_messages"`

### Requirement: Tool Input URL-Encoding and Validation

The system SHALL ensure that any user-supplied identifier
interpolated into a Graph API path segment (`message_id`, `chat_id`,
`item_id`, `site_id`, `user_id`, etc.) is URL-encoded as a path
segment via `urllib.parse.quote(value, safe="")` before being
embedded in the request path. Identifiers that contain path
separators (`/`), control characters (`\x00-\x1f`), or backslashes
SHALL be rejected with `ValueError` raised from the tool wrapper
before any HTTP call. Search strings and other free-text query
values SHALL be passed via the `params=` argument to GraphClient
(never embedded in the path) so that httpx applies query-string
encoding correctly.

#### Scenario: Path segment with slash is rejected before HTTP call

- **WHEN** an extension tool receives an `item_id` argument
  containing the substring `"a/b"`
- **THEN** the tool wrapper MUST raise `ValueError` with a message
  identifying the offending parameter
- **AND** no GET or POST MUST be issued to GraphClient

#### Scenario: Path segment with control character is rejected

- **WHEN** an extension tool receives a `message_id` argument
  containing `"\x00"` or `"\x1f"`
- **THEN** the tool wrapper MUST raise `ValueError`
- **AND** no GET or POST MUST be issued

#### Scenario: Search string is passed via params, not path

- **WHEN** an extension tool receives a `query="finance & metrics"`
  argument
- **THEN** the call to GraphClient MUST pass the value via
  `params={"$search": "finance & metrics"}`
- **AND** the value MUST NOT appear in the request path string

### Requirement: Scope Override Semantics

The system SHALL define scope-merge semantics as **REPLACE** when a
persona configures `extensions.<name>.config.scopes`: the
persona-provided list entirely supersedes the module-level default
scope constants. When the persona's `scopes` is the empty list `[]`
or absent, the default scope constants apply. There is no
merge-mode or add-to-defaults mode — a persona that wants to extend
defaults must explicitly write the full desired scope list.

This requirement disambiguates `ms-extensions` requirement language
"Default scopes include X, Y, Z" — the defaults apply only when
persona override is absent or empty.

#### Scenario: Persona scopes replace defaults entirely

- **WHEN** `persona.extensions["outlook"]["config"]["scopes"]
  == ["Mail.Read"]` (only one scope, missing Mail.Send and
  Calendars.Read which are defaults)
- **AND** the extension is constructed
- **THEN** the resulting extension's `.scopes` MUST equal exactly
  `["Mail.Read"]`
- **AND** the default scopes MUST NOT be merged in

#### Scenario: Empty persona scopes uses defaults

- **WHEN** `persona.extensions["outlook"]["config"]["scopes"] == []`
- **AND** the extension is constructed
- **THEN** the resulting extension's `.scopes` MUST equal the
  module-level default constants

#### Scenario: Missing persona scopes key uses defaults

- **WHEN** `persona.extensions["outlook"]["config"]` does not
  contain the `scopes` key at all
- **THEN** the resulting extension's `.scopes` MUST equal the
  module-level default constants

### Requirement: Tool Invocation Error When Breaker is OPEN

The system SHALL ensure that when an extension's circuit breaker is
in OPEN state and a tool is invoked, the tool raises a
`GraphAPIError` with `status_code=None` and
`error_code="breaker_open"`, surfacing the unavailability to the
agent in a structured way rather than as a generic Python exception.
The error message SHALL identify the extension by name and the
reason ("breaker open due to recent consecutive failures").

#### Scenario: Tool invocation with OPEN breaker raises structured error

- **WHEN** the breaker `extension:outlook` is OPEN
- **AND** the tool `outlook.list_messages` is invoked
- **THEN** `GraphAPIError` MUST be raised
- **AND** `error.status_code` MUST be `None`
- **AND** `error.error_code` MUST equal `"breaker_open"`
- **AND** `error.message` MUST contain the extension name `"outlook"`

### Requirement: Extension Tool Wrapping Preserves Existing Observability

The system SHALL preserve the `extension-registry` requirement that
extension `StructuredTool` invocations emit `trace_tool_call`
observability spans. The four real extensions' LangChain tools SHALL
flow through the same `wrap_extension_tools()` aggregation site
referenced by `extension-registry` and `capability-resolver`. The
real implementations SHALL NOT add tracing code at the extension
level.

#### Scenario: Real extension tool invocation still emits trace

- **WHEN** an `outlook.list_messages` LangChain tool is obtained via
  the capability-resolver aggregation site
- **AND** the tool is invoked with persona `work` and role
  `assistant`
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the emitted call's kwargs MUST include
  `tool_name="outlook.list_messages"` and `tool_kind="extension"`

### Requirement: Pagination Discipline in List Tools

The system SHALL prohibit per-item Graph fetches inside tool
implementations that loop over a `paginate()` result. Specifically,
list-tools (e.g., `outlook.list_messages`, `teams.list_chats`,
`sharepoint.list_documents`, `ms_graph.search_messages`) SHALL NOT
issue additional `GraphClient.get/post` calls for each yielded item
within the tool. When per-item enrichment is required (e.g.,
attachment metadata, read-state, sender presence), the list-tool
SHALL prefer Graph's native `$expand`/`$select` query parameters or
return a flat list and require the agent to issue an explicit
follow-up tool call. Each list-tool's docstring SHALL state the
expected upper bound on Graph API calls per invocation (e.g.,
`"<= ceil(items / page_size) Graph calls"`).

This requirement exists because Graph throttling is per-tenant and
N+1 patterns trip the `429 Retry-After` path predictably on busy
mailboxes; the cost is paid by every concurrent persona on the
tenant.

#### Scenario: list_messages does not call Graph per item

- **WHEN** `outlook.list_messages(top=50)` is invoked against a
  mocked `GraphClient` that records every `get`/`post` call
- **AND** the mocked endpoint returns 50 messages with attachments
- **THEN** the recorded `get`/`post` call count MUST be at most
  `ceil(50 / page_size) + 1` (one per page; the `+1` covers an
  optional `$expand` resolution)
- **AND** the call count MUST NOT scale linearly with the number of
  messages

### Requirement: Per-Tool Page Ceiling Configuration

The system SHALL allow each list-tool implementation to override the
default `GraphClient.page_ceiling=100` by passing an explicit
`page_ceiling` to `paginate()` at call sites where larger result
sets are expected (e.g., `outlook.list_messages` over a year-long
mailbox). The tool SHALL document its effective ceiling in the
LangChain `description` field of the `StructuredTool` so agents
know when results may be truncated. When a tool does not override
the default, its `description` SHALL state that results larger than
100 pages will raise `GraphAPIError(error_code="page_ceiling_exceeded")`
and recommend narrowing the query.

#### Scenario: list_messages declares its page_ceiling in tool description

- **WHEN** `outlook.list_messages` is exposed as a LangChain
  `StructuredTool`
- **THEN** the tool's `description` MUST contain the substring
  `"page_ceiling"` followed by the effective integer value
- **AND** if the value differs from the GraphClient default (100),
  the difference MUST be visible in the description text
