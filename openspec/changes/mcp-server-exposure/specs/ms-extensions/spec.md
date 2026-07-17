# ms-extensions Specification (delta)

## REMOVED Requirements

### Requirement: Tool Format Parity Between LangChain and MSAF

**Reason**: The dual-format authoring it guarded no longer exists.
Extensions emit one harness-neutral `tool_specs()` list (P17
tool-spec migration); the per-harness adapters render it, so
cross-harness drift is impossible by construction. The adapter purity
contract lives in the `tool-spec` capability ("Adapters do not change
the tool set").

## MODIFIED Requirements

### Requirement: ms_graph Extension Real Implementation

The system SHALL replace the `ms_graph` stub at
`src/assistant/extensions/ms_graph.py` with a real implementation that
exposes generic Microsoft Graph tools (people search, profile read,
cross-mailbox message search). The extension SHALL accept a
`GraphClient` instance at construction. `tool_specs()` SHALL return a
non-empty `ToolSpec` list when the persona enables this extension,
with `source="extension:ms_graph"` on every spec.

#### Scenario: tool_specs returns non-empty list

- **WHEN** `create_extension(config={}, client=mock_client).tool_specs()`
  is called
- **THEN** the returned list MUST contain at least three `ToolSpec`
  instances
- **AND** the spec names MUST include `ms_graph.search_people`,
  `ms_graph.get_my_profile`, `ms_graph.search_messages`

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
write tool, surfaced as `ToolSpec` instances via `tool_specs()`. The
extension SHALL accept a `GraphClient` instance at construction.

#### Scenario: Tool list includes read and write tools

- **WHEN** `create_extension({}, client=mock_client).tool_specs()`
  is called
- **THEN** the returned list MUST include at least the specs
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
write tool, surfaced as `ToolSpec` instances via `tool_specs()`.

#### Scenario: Tool list includes read and write tools

- **WHEN** `create_extension({}, client=mock_client).tool_specs()`
  is called
- **THEN** the returned list MUST include at least the specs
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
exposing SharePoint search and document read tools, surfaced as
`ToolSpec` instances via `tool_specs()`. SharePoint write-side tools
(list-item create, document upload) are explicitly deferred to a P5b
follow-up. The `download_document` tool SHALL use the
`CloudGraphClient.get_bytes()` method (50 MiB ceiling by default)
to retrieve binary content; the tool MUST return the result dict
structure `{"path", "size_bytes", "content_type", "request_id"}`
specified in the `graph-client` capability and MUST NOT return raw
bytes in memory.

#### Scenario: Tool list contains only read tools

- **WHEN** `create_extension({}, client=mock_client).tool_specs()`
  is called
- **THEN** the returned list MUST include `sharepoint.search_sites`,
  `sharepoint.list_documents`, `sharepoint.download_document`
- **AND** no spec name MUST start with `sharepoint.create` or
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

### Requirement: Extension Tool Wrapping Preserves Existing Observability

The system SHALL preserve the `extension-registry` requirement that
extension tool invocations emit `trace_tool_call` observability
spans. The four real extensions' `ToolSpec`s SHALL flow through the
same `wrap_extension_tool_specs()` aggregation site referenced by
`extension-registry` and `capability-resolver`. The real
implementations SHALL NOT add tracing code at the extension level.

#### Scenario: Real extension tool invocation still emits trace

- **WHEN** an `outlook.list_messages` ToolSpec is obtained via
  the capability-resolver aggregation site
- **AND** its handler is awaited with persona `work` and role
  `assistant`
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the emitted call's kwargs MUST include
  `tool_name="outlook.list_messages"` and `tool_kind="extension"`
