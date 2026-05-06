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
deferred to a P5b follow-up.

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
