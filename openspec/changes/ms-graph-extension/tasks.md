# Implementation Tasks — ms-graph-extension

Task ordering follows the work-packages DAG declared in
`work-packages.yaml`:

1. `wp-foundation` MUST land first (gates the four extension packages
   and the harness package).
2. `wp-ms-graph`, `wp-outlook`, `wp-teams`, `wp-sharepoint`,
   `wp-msaf-harness` are independent of each other and run in parallel.
3. `wp-integration` runs last; it updates existing test files that
   assert stub behavior for the four MS extensions.

Within each work package, tests precede implementation per TDD
discipline. Each test task references the spec scenarios it encodes
and any design decision IDs (D1–D12 in `design.md`) it verifies.

## 1. wp-foundation — Cloud client Protocol + MSAL + GraphClient

- [ ] 1.1 Write tests for `CloudGraphClient` Protocol shape
  **Spec scenarios**: graph-client / "Protocol declares four required
  methods", "Custom GraphClient satisfies Protocol", "MockGraphClient
  satisfies Protocol"
  **Design decisions**: D3 (CloudGraphClient Protocol shape)
  **Dependencies**: None
- [ ] 1.2 Create `src/assistant/core/cloud_client.py` —
  `CloudGraphClient` Protocol with `get`, `post`, `paginate`,
  `health_check`
  **Dependencies**: 1.1

- [ ] 1.3 Write tests for `MSALStrategy` Protocol +
  `InteractiveDelegatedStrategy` (mock `msal.PublicClientApplication`)
  **Spec scenarios**: msal-auth / "Protocol returns access token
  string", "Protocol is runtime-checkable", "First call opens
  interactive flow when cache is empty", "Subsequent call uses silent
  flow", "Silent failure falls back to interactive", "force_refresh
  bypasses silent flow", "Device-code fallback when
  MSAL_FALLBACK_DEVICE_CODE is set"
  **Design decisions**: D1 (Two pluggable MSAL strategies)
  **Dependencies**: 1.2

- [ ] 1.4 Write tests for `ClientCredentialsStrategy` (mock
  `msal.ConfidentialClientApplication`)
  **Spec scenarios**: msal-auth / "Strategy uses
  ConfidentialClientApplication", "Strategy rejects user-scoped
  scopes"
  **Design decisions**: D1
  **Dependencies**: 1.2

- [ ] 1.5 Write tests for token cache file discipline (tmpfile
  rename, mode 0o600, missing-file empty cache, permission audit)
  **Spec scenarios**: msal-auth / "First write creates directory with
  restrictive permissions", "File is written with mode 0o600",
  "Atomic write via tmp + rename", "Missing cache file yields empty
  cache without error", "Permission audit fails fast on broken
  filesystem state"
  **Design decisions**: D2 (Per-persona token cache file with
  restrictive permissions)
  **Dependencies**: 1.2

- [ ] 1.6 Write tests for `create_msal_strategy` factory
  **Spec scenarios**: msal-auth / "interactive flow returns
  InteractiveDelegatedStrategy", "client_credentials flow returns
  ClientCredentialsStrategy", "Missing required env raises with
  actionable message"
  **Design decisions**: D1, D8 (Persona auth schema)
  **Dependencies**: 1.3, 1.4

- [ ] 1.7 Write tests asserting auth errors do NOT retry
  **Spec scenarios**: msal-auth / "401-equivalent auth error
  propagates without retry", "Error string is sanitized"
  **Design decisions**: D9 (Error handling boundaries)
  **Dependencies**: 1.3, 1.4

- [ ] 1.8 Create `src/assistant/core/msal_auth.py` — `MSALStrategy`
  Protocol, `InteractiveDelegatedStrategy`,
  `ClientCredentialsStrategy`, `create_msal_strategy`,
  `MSALAuthenticationError`
  **Dependencies**: 1.3, 1.4, 1.5, 1.6, 1.7

- [ ] 1.9 Write tests for `GraphClient` GET/POST request shape
  (Bearer header, JSON body, parsed response)
  **Spec scenarios**: graph-client / "Constructor stores
  extension_name and strategy", "GET request attaches Authorization
  Bearer header", "GET request returns parsed JSON body", "POST
  request sends JSON body and returns parsed response"
  **Design decisions**: D4 (GraphClient implementation)
  **Dependencies**: 1.2, 1.8

- [ ] 1.10 Write tests for `paginate()` (`@odata.nextLink`-chasing,
  page ceiling, header preservation)
  **Spec scenarios**: graph-client / "Paginate yields successive
  pages until nextLink absent", "nextLink chase preserves header and
  base URL", "Page ceiling triggers termination with warning"
  **Design decisions**: D4
  **Dependencies**: 1.2

- [ ] 1.11 Write tests for resilience integration (per-extension
  breaker namespace + isolation)
  **Spec scenarios**: graph-client / "Breaker key derived from
  extension_name", "Breaker open on one extension does not affect
  another"
  **Design decisions**: D4, D9
  **Dependencies**: 1.2

- [ ] 1.12 Write tests for 401 token refresh + replay
  **Spec scenarios**: graph-client / "401 response triggers
  force_refresh and retry", "Second 401 propagates as
  MSALAuthenticationError"
  **Design decisions**: D9
  **Dependencies**: 1.2, 1.8

- [ ] 1.13 Write tests for `GraphAPIError` sanitization +
  `health_check`
  **Spec scenarios**: graph-client / "Non-2xx response raises
  GraphAPIError with status_code", "Authorization header value is
  sanitized in error string", "CLOSED breaker yields OK
  HealthStatus", "OPEN breaker yields UNAVAILABLE HealthStatus"
  **Design decisions**: D9
  **Dependencies**: 1.2

- [ ] 1.14 Create `src/assistant/core/graph_client.py` —
  `GraphClient`, `GraphAPIError`, request/pagination/auth-refresh
  helpers, breaker integration
  **Dependencies**: 1.9, 1.10, 1.11, 1.12, 1.13

- [ ] 1.15 Create `tests/mocks/graph_client.py` — `MockGraphClient`
  satisfying `CloudGraphClient` with method-level patch hooks
  **Spec scenarios**: graph-client / "MockGraphClient satisfies
  Protocol"
  **Design decisions**: D7 (Test infrastructure)
  **Dependencies**: 1.2

- [ ] 1.16 Add `msal>=1.28` and `respx>=0.21` to `pyproject.toml`;
  run `uv sync` to lock
  **Dependencies**: 1.8, 1.15

## 2. wp-ms-graph — Real ms_graph extension

- [ ] 2.1 Write tests for `ms_graph` extension tool surface (presence,
  names, dual-format parity)
  **Spec scenarios**: ms-extensions / "as_langchain_tools returns
  non-empty list", "as_ms_agent_tools returns non-empty list", "Tool
  counts match across formats", "Tool names match by index"
  **Design decisions**: D6 (Extension internal structure), D11 (Tool
  format conversion is per-extension)
  **Dependencies**: 1.14, 1.15

- [ ] 2.2 Write tests for `search_people`, `get_my_profile`,
  `search_messages` against `MockGraphClient`
  **Spec scenarios**: ms-extensions / "search_people calls /users
  with $search and returns parsed value list", "Default scopes
  include People.Read and User.Read"
  **Dependencies**: 1.14, 1.15

- [ ] 2.3 Write tests for `ms_graph` HealthStatus derivation
  **Spec scenarios**: ms-extensions / "Real extension reports OK
  when breaker is CLOSED", "Real extension reports UNAVAILABLE when
  breaker is OPEN"; extension-registry / "Real extension derives
  HealthStatus from its breaker"
  **Dependencies**: 1.14

- [ ] 2.4 Replace `src/assistant/extensions/ms_graph.py` stub with
  real implementation: `MsGraphExtension` class, default scopes,
  three tools (`search_people`, `get_my_profile`, `search_messages`),
  dual-format wrappers, `health_check` from breaker
  **Dependencies**: 2.1, 2.2, 2.3

- [ ] 2.5 Add `tests/fixtures/graph_responses/ms_graph/` JSON
  fixtures with `// FIXTURE_GRAPH_RESPONSE_v1` sentinel
  **Dependencies**: None (lands alongside 2.4)

## 3. wp-outlook — Real outlook extension

- [ ] 3.1 Write tests for outlook tool surface (read + write, dual
  format)
  **Spec scenarios**: ms-extensions / "Tool list includes read and
  write tools", "Tool counts match across formats"
  **Design decisions**: D6, D11
  **Dependencies**: 1.14, 1.15

- [ ] 3.2 Write tests for `list_messages`, `read_message`,
  `search_messages`, `list_calendar_events`, `find_free_times`
  against `MockGraphClient`
  **Spec scenarios**: ms-extensions / "list_messages calls
  /me/messages and returns value array", "Default scopes include
  Mail.Read, Mail.Send, and Calendars.Read"
  **Dependencies**: 1.14, 1.15

- [ ] 3.3 Write tests for `send_email` write tool body shape
  **Spec scenarios**: ms-extensions / "send_email POSTs to
  /me/sendMail with the expected body shape"
  **Dependencies**: 1.14, 1.15

- [ ] 3.4 Write tests for outlook HealthStatus derivation
  **Spec scenarios**: ms-extensions / "Real extension reports OK
  when breaker is CLOSED", "Real extension reports UNAVAILABLE when
  breaker is OPEN"
  **Dependencies**: 1.14

- [ ] 3.5 Replace `src/assistant/extensions/outlook.py` stub with
  real `OutlookExtension`: six tools, default scopes, dual wrappers,
  health_check from breaker
  **Dependencies**: 3.1, 3.2, 3.3, 3.4

- [ ] 3.6 Add `tests/fixtures/graph_responses/outlook/` JSON fixtures
  **Dependencies**: None

## 4. wp-teams — Real teams extension

- [ ] 4.1 Write tests for teams tool surface (read + write, dual
  format)
  **Spec scenarios**: ms-extensions / "Tool list includes read and
  write tools" (teams), "Tool counts match across formats"
  **Design decisions**: D6, D11
  **Dependencies**: 1.14, 1.15

- [ ] 4.2 Write tests for `list_chats`, `list_channel_messages`,
  `read_message` against `MockGraphClient`
  **Spec scenarios**: ms-extensions / "list_chats calls /me/chats
  and returns value array", "Default scopes include Chat.Read,
  Chat.ReadWrite, ChannelMessage.Read.All"
  **Dependencies**: 1.14, 1.15

- [ ] 4.3 Write tests for `post_chat_message` body shape
  **Spec scenarios**: ms-extensions / "post_chat_message POSTs to
  /chats/{chatId}/messages"
  **Dependencies**: 1.14, 1.15

- [ ] 4.4 Write tests for teams HealthStatus derivation
  **Dependencies**: 1.14

- [ ] 4.5 Replace `src/assistant/extensions/teams.py` stub with
  real `TeamsExtension`
  **Dependencies**: 4.1, 4.2, 4.3, 4.4

- [ ] 4.6 Add `tests/fixtures/graph_responses/teams/` JSON fixtures
  **Dependencies**: None

## 5. wp-sharepoint — Real sharepoint extension (read-only)

- [ ] 5.1 Write tests asserting NO write tools are present
  **Spec scenarios**: ms-extensions / "Tool list contains only read
  tools"
  **Design decisions**: D6
  **Dependencies**: 1.14, 1.15

- [ ] 5.2 Write tests for `search_sites`, `list_documents`,
  `download_document` against `MockGraphClient`
  **Spec scenarios**: ms-extensions / "search_sites calls /sites
  with $search", "Default scopes include Sites.Read.All and
  Files.Read.All"
  **Dependencies**: 1.14, 1.15

- [ ] 5.3 Write tests for sharepoint HealthStatus derivation
  **Dependencies**: 1.14

- [ ] 5.4 Replace `src/assistant/extensions/sharepoint.py` stub with
  real `SharepointExtension` (read-only)
  **Dependencies**: 5.1, 5.2, 5.3

- [ ] 5.5 Add `tests/fixtures/graph_responses/sharepoint/` JSON
  fixtures
  **Dependencies**: None

## 6. wp-msaf-harness — MS Agent Framework harness implementation

- [ ] 6.1 Write tests asserting `MSAgentFrameworkHarness.create_agent`
  no longer raises NotImplementedError and returns
  `agent_framework.Agent`
  **Spec scenarios**: ms-agent-framework-harness / "Harness is
  registered and instantiable", "create_agent no longer raises
  NotImplementedError"
  **Design decisions**: D5 (MSAF SDK is agent-framework)
  **Dependencies**: 1.14

- [ ] 6.2 Write tests for `create_agent` instructions composition +
  tool union
  **Spec scenarios**: ms-agent-framework-harness / "Agent receives
  composed instructions", "Agent receives extension tools via
  as_ms_agent_tools", "Chat client selection respects persona
  configuration"
  **Design decisions**: D5, D11
  **Dependencies**: 1.14

- [ ] 6.3 Write tests for `invoke` returning string + exception
  propagation
  **Spec scenarios**: ms-agent-framework-harness / "invoke returns
  the agent's response string", "invoke propagates underlying
  exceptions unchanged"
  **Design decisions**: D5
  **Dependencies**: 1.14

- [ ] 6.4 Write tests for `spawn_sub_agent` (sub-role prompt, return
  value)
  **Spec scenarios**: ms-agent-framework-harness / "spawn_sub_agent
  returns the sub-agent's response", "Sub-agent uses sub-role's
  composed prompt"
  **Design decisions**: D5
  **Dependencies**: 1.14

- [ ] 6.5 Write tests for capability consumption (ToolPolicy,
  GuardrailProvider; assert MemoryPolicy is NOT consumed)
  **Spec scenarios**: ms-agent-framework-harness / "Authorized
  extensions are filtered through ToolPolicy",
  "spawn_sub_agent calls GuardrailProvider before constructing
  sub-agent"
  **Design decisions**: D10 (Capability resolver wiring for MSAF)
  **Dependencies**: 1.14

- [ ] 6.6 Write tests for `@traced_harness` decorator integration on
  the now-real invoke path
  **Spec scenarios**: ms-agent-framework-harness / "Successful invoke
  emits trace_llm_call once", "Failed invoke still emits
  trace_llm_call before propagating"; harness-adapter delta /
  "MSAgentFrameworkHarness invoke emits trace on the success path",
  "MSAgentFrameworkHarness exception path still emits trace"
  **Dependencies**: 1.14

- [ ] 6.7 Replace `src/assistant/harnesses/sdk/ms_agent_fw.py` stub
  with full implementation: agent construction, invoke, sub-agent
  spawn, capability resolver wiring, traced decorator
  **Dependencies**: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6

- [ ] 6.8 Add `agent-framework` to `pyproject.toml`; verify version
  via Context7 at implementation time; run `uv sync`
  **Dependencies**: 6.7

## 7. wp-integration — Cross-cutting test updates and final validation

- [ ] 7.1 Locate existing tests asserting `ms_graph`/`teams`/
  `sharepoint`/`outlook` return empty tool lists; update to assert
  real-implementation behavior
  **Spec scenarios**: extension-registry / "ms_graph/teams/sharepoint/
  outlook no longer return empty tool lists", "Real extension
  derives HealthStatus from its breaker"
  **Dependencies**: 2.4, 3.5, 4.5, 5.4

- [ ] 7.2 Locate existing tests asserting
  `MSAgentFrameworkHarness.create_agent` raises
  `NotImplementedError`; update to assert real implementation
  **Spec scenarios**: ms-agent-framework-harness / "create_agent no
  longer raises NotImplementedError"; harness-adapter delta REMOVED
  requirement
  **Dependencies**: 6.7

- [ ] 7.3 Update `personas/_template/.gitignore` to add `.cache/` so
  token cache files never get committed
  **Design decisions**: D2
  **Dependencies**: None

- [ ] 7.4 Add a startup check (or test) that asserts
  `personas/<name>/.cache/` permission audit catches `0o077` mode
  bits before writing
  **Spec scenarios**: msal-auth / "Permission audit fails fast on
  broken filesystem state"
  **Dependencies**: 1.8

- [ ] 7.5 Add `tests/test_extensions_dual_format.py` parameterized
  test covering all four real extensions for tool-count + name parity
  **Spec scenarios**: ms-extensions / "Tool counts match across
  formats", "Tool names match by index"
  **Dependencies**: 2.4, 3.5, 4.5, 5.4

- [ ] 7.6 Add opt-in `tests/integration/test_graph_smoke.py` (gated
  on `RUN_GRAPH_TESTS=1`)
  **Design decisions**: D7
  **Dependencies**: 6.7

- [ ] 7.7 Update `openspec/roadmap.md` to flip P5 from `pending` to
  `archived` (will land in archival commit). Also flip P4
  `observability` from `pending` to `archived` (currently drifted —
  archive directory exists but roadmap row says pending). Note: this
  is a hygiene fix only; observability has been archived since
  2026-05-03.
  **Dependencies**: All other tasks

- [ ] 7.8 Run quality gates per "Landing the Plane" (CLAUDE.md):
  `uv run pytest tests/`, `uv run ruff check src tests`,
  `uv run mypy src tests`, `openspec validate ms-graph-extension
  --strict`
  **Dependencies**: 7.1, 7.2, 7.3, 7.4, 7.5

- [ ] 7.9 File P5b follow-up issues for deferred scope:
  SharePoint writes, Outlook calendar event creation, Teams meeting
  creation, MSAF MemoryPolicy wiring
  **Dependencies**: 7.8
