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
  **Spec scenarios**: graph-client / "Protocol declares five required
  methods", "Custom GraphClient satisfies Protocol", "MockGraphClient
  satisfies Protocol"
  **Design decisions**: D3 (CloudGraphClient Protocol shape), D19
  (`get_bytes` streaming download)
  **Dependencies**: None
- [ ] 1.2 Create `src/assistant/core/cloud_client.py` —
  `CloudGraphClient` Protocol with `get`, `post`, `paginate`,
  `get_bytes`, `health_check`
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
  page ceiling raises, header preservation)
  **Spec scenarios**: graph-client / "Paginate yields successive
  pages until nextLink absent", "nextLink chase preserves header and
  base URL", "Page ceiling raises rather than terminates silently",
  "Page ceiling is configurable"
  **Design decisions**: D4, D19 (page ceiling supersedes silent
  truncation)
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
  GuardrailProvider, MemoryPolicy minimal-prepend injection)
  **Spec scenarios**: ms-agent-framework-harness / "Authorized
  extensions are filtered through ToolPolicy",
  "spawn_sub_agent calls GuardrailProvider before constructing
  sub-agent", "Memory snippets prepended to instructions",
  "Empty memory snippets leaves instructions unchanged",
  "NoopMemoryPolicy yields no injection"
  **Design decisions**: D10 (Capability resolver wiring for MSAF;
  MemoryPolicy now minimally consumed per D27), D27 (Minimal
  MemoryPolicy injection)
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
  creation, full-fidelity MSAF MemoryPolicy hook (when
  agent-framework SDK exposes one)
  **Dependencies**: 7.8

## 8. Post-review remediation tasks

Tasks added in response to the parallel-review-plan multi-vendor
review (claude + codex + gemini). Each task references the design
decision (D13–D27) and spec scenario(s) it implements. Tasks are
grouped by work package — assignees fold them into the existing
package work.

### 8.1 wp-foundation additions

- [ ] 8.1.1 Write tests for Retry-After honoring on 429 and 503
  (delta-seconds form, HTTP-date form, no-header fallback)
  **Spec scenarios**: graph-client / "429 with delta-seconds
  Retry-After delays retry", "503 with HTTP-date Retry-After delays
  retry", "429 without Retry-After falls through to default
  backoff"
  **Design decisions**: D13
  **Dependencies**: 1.14

- [ ] 8.1.2 Implement Retry-After honoring in GraphClient (parse
  header, sleep up to indicated value before P9 backoff applies)
  **Dependencies**: 8.1.1

- [ ] 8.1.3 Write tests for per-request httpx.Timeout default
  (connect=10, read=30, write=30, pool=5) and read-timeout raising
  GraphAPIError
  **Spec scenarios**: graph-client / "Default timeout values
  applied", "Read timeout raises GraphAPIError"
  **Design decisions**: D14
  **Dependencies**: 1.14

- [ ] 8.1.4 Implement timeout configuration in GraphClient
  constructor; pass to httpx.AsyncClient
  **Dependencies**: 8.1.3

- [ ] 8.1.5 Write tests for trace_graph_call observability span
  (one per request, 401-then-success emits two, path normalization
  redacts IDs)
  **Spec scenarios**: graph-client / "Successful GET emits one
  trace_graph_call span", "401-then-success emits two spans",
  "Path normalization redacts message_id-shaped segments"
  **Design decisions**: D15
  **Dependencies**: 1.14

- [ ] 8.1.6 Add `trace_graph_call(...)` method to the P4
  observability provider interface; implement in noop and
  Langfuse providers; wire into GraphClient request loop
  **Dependencies**: 8.1.5

- [ ] 8.1.7 Write tests for empty 202/204 body handling (POST returns
  empty dict, GET 204 returns empty dict, 200 with zero-length JSON
  body returns empty dict)
  **Spec scenarios**: graph-client / "202 empty body returns empty
  dict", "204 empty body returns empty dict", "200 with empty
  JSON-Content-Type body returns empty dict"
  **Design decisions**: D16
  **Dependencies**: 1.14

- [ ] 8.1.8 Implement empty-body handling in GraphClient.get/post —
  short-circuit JSON parsing for 202/204/empty-body 200 responses
  **Dependencies**: 8.1.7

- [ ] 8.1.9 Write tests confirming GraphAPIError subclasses
  httpx.HTTPStatusError and that 5xx triggers P9 retry
  **Spec scenarios**: graph-client / "GraphAPIError is an
  httpx.HTTPStatusError", "5xx GraphAPIError triggers P9 retry"
  **Design decisions**: D17
  **Dependencies**: 1.14

- [ ] 8.1.10 Refactor GraphAPIError to extend httpx.HTTPStatusError
  (preserve typed error_code, request_id, message fields while
  satisfying P9's classifier)
  **Dependencies**: 8.1.9

- [ ] 8.1.11 Write tests for retry_safe parameter (False bypasses
  P9, True default retries on 5xx, breaker still records on both
  paths)
  **Spec scenarios**: graph-client / "retry_safe=False bypasses P9
  retry", "retry_safe=True (default) retries on 5xx"
  **Design decisions**: D18
  **Dependencies**: 1.14

- [ ] 8.1.12 Implement retry_safe parameter on
  CloudGraphClient.post and GraphClient.post — split into two
  internal paths (retrying vs non-retrying); both record breaker
  state on failure
  **Dependencies**: 8.1.11

- [ ] 8.1.13 Write tests for get_bytes (download to tempfile,
  metadata dict shape, max_bytes ceiling aborts and cleans up,
  resilience+observability wrapping)
  **Spec scenarios**: graph-client / "Successful download returns
  path + metadata dict", "Download exceeding max_bytes aborts with
  size_exceeded", "get_bytes wraps with same resilience and
  observability layers"
  **Design decisions**: D19
  **Dependencies**: 1.14

- [ ] 8.1.14 Implement CloudGraphClient.get_bytes (Protocol) and
  GraphClient.get_bytes (impl) — streaming download, max_bytes
  enforcement, tempfile result, partial cleanup on abort
  **Dependencies**: 8.1.13

- [ ] 8.1.15 Write tests for paginate raising on page_ceiling
  exceeded (default 100, configurable 500)
  **Spec scenarios**: graph-client / "Page ceiling raises rather
  than terminates silently", "Page ceiling is configurable"
  **Design decisions**: D19 (paginate ceiling fix bundled here)
  **Dependencies**: 1.14

- [ ] 8.1.16 Refactor paginate to raise GraphAPIError(error_code=
  "page_ceiling_exceeded") on ceiling, after warning log, instead
  of yielding-and-returning
  **Dependencies**: 8.1.15

- [ ] 8.1.17 Write tests for asyncio.to_thread wrapping of MSAL sync
  calls (concurrent acquire_token does not serialize)
  **Spec scenarios**: msal-auth / "acquire_token wraps synchronous
  MSAL call in to_thread", "Concurrent Graph calls are not
  serialized by MSAL"
  **Design decisions**: D20
  **Dependencies**: 1.8

- [ ] 8.1.18 Wrap all synchronous MSAL calls in
  InteractiveDelegatedStrategy and ClientCredentialsStrategy with
  asyncio.to_thread
  **Dependencies**: 8.1.17

- [ ] 8.1.19 Write tests for atomic tmp-file mode 0o600 creation
  via os.open with O_CREAT|O_WRONLY|O_EXCL, refusal to overwrite
  stale tmp file
  **Spec scenarios**: msal-auth / "Tmp file is created with mode
  0o600 atomically"
  **Design decisions**: D21
  **Dependencies**: 1.8

- [ ] 8.1.20 Refactor token cache write path to use os.open with
  the right mode flags from creation; fail-fast on stale tmp
  **Dependencies**: 8.1.19

- [ ] 8.1.21 Write tests for persona-repo .gitignore verification
  (missing entry blocks write, present entry allows write)
  **Spec scenarios**: msal-auth / "Missing gitignore entry blocks
  token write", "Present gitignore entry allows token write"
  **Design decisions**: D22
  **Dependencies**: 1.8

- [ ] 8.1.22 Implement gitignore check before any token cache
  write; fail with MSALAuthenticationError when missing
  **Dependencies**: 8.1.21

- [ ] 8.1.23 Update msal-auth factory to read auth.ms via
  persona.raw rather than typed PersonaConfig fields
  **Spec scenarios**: msal-auth / "Strategy Selection by Persona
  Configuration" requirement
  **Design decisions**: D8 (clarification)
  **Dependencies**: 1.8

### 8.2 wp-ms-graph / wp-outlook / wp-teams / wp-sharepoint additions

- [ ] 8.2.1 Write tests for tool input URL-encoding and validation
  (path-separator rejection, control-char rejection, search via
  params)
  **Spec scenarios**: ms-extensions / "Path segment with slash is
  rejected before HTTP call", "Path segment with control character
  is rejected", "Search string is passed via params, not path"
  **Design decisions**: D23
  **Dependencies**: 1.14
  Applies to: each of 2.x (ms_graph), 3.x (outlook), 4.x (teams),
  5.x (sharepoint)

- [ ] 8.2.2 Implement URL-encoding helper (urllib.parse.quote with
  safe="") and input validator; use in every tool that interpolates
  IDs into paths
  **Dependencies**: 8.2.1
  Applies to: 2.4, 3.5, 4.5, 5.4

- [ ] 8.2.3 Write tests for scope override REPLACE semantics
  (persona scopes replace defaults, empty list uses defaults,
  missing key uses defaults)
  **Spec scenarios**: ms-extensions / "Persona scopes replace
  defaults entirely", "Empty persona scopes uses defaults",
  "Missing persona scopes key uses defaults"
  **Design decisions**: D24
  **Dependencies**: 1.14
  Applies to: each extension

- [ ] 8.2.4 Implement scope resolution helper using REPLACE
  semantics; use in all four real extension constructors
  **Dependencies**: 8.2.3
  Applies to: 2.4, 3.5, 4.5, 5.4

- [ ] 8.2.5 Write tests for tool invocation with OPEN breaker
  raising GraphAPIError(error_code="breaker_open")
  **Spec scenarios**: ms-extensions / "Tool invocation with OPEN
  breaker raises structured error"
  **Design decisions**: D25
  **Dependencies**: 1.14
  Applies to: each extension

- [ ] 8.2.6 Wrap each extension's tool method with breaker-state
  check; raise structured error when breaker is OPEN
  **Dependencies**: 8.2.5
  Applies to: 2.4, 3.5, 4.5, 5.4

- [ ] 8.2.7 (outlook) Update _send_email to pass retry_safe=False
  when calling client.post
  **Spec scenarios**: graph-client / "retry_safe=False bypasses
  P9 retry" (consumer)
  **Design decisions**: D18
  **Dependencies**: 8.1.12
  Applies to: 3.5

- [ ] 8.2.8 (teams) Update _post_chat_message to pass
  retry_safe=False when calling client.post
  **Design decisions**: D18
  **Dependencies**: 8.1.12
  Applies to: 4.5

- [ ] 8.2.9 (sharepoint) Update _download_document to call
  client.get_bytes (replacing the original spec scenario that
  expected get to return bytes)
  **Spec scenarios**: ms-extensions / "download_document delegates
  to get_bytes and returns metadata dict"
  **Design decisions**: D19
  **Dependencies**: 8.1.14
  Applies to: 5.4

### 8.3 wp-msaf-harness additions

- [ ] 8.3.1 Write tests for MemoryPolicy snippet injection (snippets
  prepended under "## Recent context" heading, empty list leaves
  unchanged, noop policy yields no injection)
  **Spec scenarios**: ms-agent-framework-harness / "Memory snippets
  prepended to instructions", "Empty memory snippets leaves
  instructions unchanged", "NoopMemoryPolicy yields no injection"
  **Design decisions**: D27
  **Dependencies**: 1.14, 6.7

- [ ] 8.3.2 Implement MemoryPolicy.get_recent_snippets call in
  MSAgentFrameworkHarness.create_agent; prepend snippets to
  instructions under "## Recent context" heading
  **Dependencies**: 8.3.1

### 8.4 wp-foundation: extension factory contract

- [ ] 8.4.1 Write tests for extended factory contract
  (PersonaRegistry passes persona kwarg to all factories, real
  factories build MSAL+GraphClient internally, stubs ignore
  persona, third-party legacy signature raises actionable
  TypeError)
  **Spec scenarios**: extension-registry / "PersonaRegistry passes
  persona to all factories", "Real factory constructs MSALStrategy
  and GraphClient internally", "Stub factory ignores persona
  argument", "Legacy factory signature raises actionable TypeError"
  **Design decisions**: D26
  **Dependencies**: 1.14

- [ ] 8.4.2 Refactor `create_extension` factory contract across
  all seven extension modules to accept `*, persona: PersonaConfig
  | None = None`. Stubs (gmail/gcal/gdrive) accept and ignore.
  Real factories (ms_graph/outlook/teams/sharepoint) call
  `create_msal_strategy(persona)` and construct GraphClient.
  **Dependencies**: 8.4.1, 1.8, 1.14

- [ ] 8.4.3 Update PersonaRegistry.load_extensions to pass
  `persona=<the persona>` to every `create_extension` call;
  catch TypeError from legacy factories and re-raise with
  actionable message
  **Dependencies**: 8.4.1
  Belongs in wp-foundation since it touches core/persona.py

### 8.5 wp-integration additions

- [ ] 8.5.1 Verify the dual-format parity test (existing 7.5)
  also covers: tools that take ID arguments validate them,
  tools that take search arguments pass via params=, breaker-
  open path raises consistently across all four extensions
  **Dependencies**: 8.2.6, 7.5

- [ ] 8.5.2 Add an integration smoke test for download_document
  exercising get_bytes streaming + tempfile cleanup against
  MockGraphClient (no real Graph required)
  **Dependencies**: 8.1.14, 5.4

- [ ] 8.5.3 Add a section to CLAUDE.md "What's Not Yet Wired"
  documenting that MSAF memory injection is the minimal-viable
  prepend-to-instructions form; full MemoryPolicy hook awaits
  agent-framework SDK support
  **Dependencies**: 8.3.2

## 9. PLAN_ITERATE remediation tasks

This section captures work uncovered during the autopilot
PLAN_ITERATE pass after round-1 PLAN_REVIEW remediation: D19's
fifth Protocol method exposed downstream stale references; the
post-remediation plan was missing security-critical lifecycle and
redirect-rejection requirements; the trace_graph_call observability
contract was specified in graph-client/spec.md but missing from the
ObservabilityProvider Protocol itself; the work-packages.yaml had a
stale path to the observability provider module. Each task here
folds into one of the existing work packages.

### 9.1 wp-foundation additions (observability + redirect + lifecycle)

- [ ] 9.1.1 Write tests for `ObservabilityProvider.trace_graph_call`
  Protocol method on `NoopProvider` and `LangfuseProvider`
  (NoopProvider returns None silently; LangfuseProvider emits one
  Langfuse span with all kwargs as attributes; resilience composition
  emits one trace_graph_call per HTTP attempt; OPEN breaker emits no
  trace_graph_call but does emit `start_span("resilience.short_circuit")`)
  **Spec scenarios**: observability / "NoopProvider implements
  trace_graph_call", "LangfuseProvider implements trace_graph_call",
  "trace_graph_call records error class on failure", "Successful
  retry emits one trace_graph_call per attempt", "Open breaker emits
  no trace_graph_call"
  **Design decisions**: D15
  **Dependencies**: 1.14
  Belongs in wp-foundation: writes to
  `tests/test_observability_trace_graph_call.py`

- [ ] 9.1.2 Add `trace_graph_call(...)` to `ObservabilityProvider`
  Protocol in `src/assistant/telemetry/providers/base.py`; implement
  noop in `src/assistant/telemetry/providers/noop.py`; implement
  langfuse in `src/assistant/telemetry/providers/langfuse.py`. This
  supersedes the prior task 8.1.6 which referenced a non-existent
  `core/observability.py` path.
  **Dependencies**: 9.1.1
  Belongs in wp-foundation.

- [ ] 9.1.3 Write tests for `GraphClient` async context-manager and
  explicit `aclose()` (entry/exit semantics, idempotent close,
  closed client raises on use)
  **Spec scenarios**: graph-client / "Async context-manager closes
  the underlying httpx client", "Explicit aclose closes the
  underlying httpx client"
  **Design decisions**: D4
  **Dependencies**: 1.13

- [ ] 9.1.4 Implement `__aenter__`/`__aexit__`/`aclose` on
  `GraphClient`; ensure all PersonaRegistry construction sites use
  `async with` or arrange explicit `aclose()` before process exit
  **Dependencies**: 9.1.3

- [ ] 9.1.5 Write tests for cross-domain redirect rejection
  (trusted host follow, untrusted-host nextLink rejected before
  bearer attached, 3xx not auto-followed)
  **Spec scenarios**: graph-client / "Pagination nextLink to
  graph.microsoft.com is followed", "Pagination nextLink to
  non-trusted host is rejected", "HTTP 3xx response is not
  auto-followed"
  **Design decisions**: D4
  **Dependencies**: 1.10

- [ ] 9.1.6 Implement trusted-host validation in `GraphClient`
  (`trusted_hosts: list[str] | None = None` constructor arg with
  default; `httpx.AsyncClient(follow_redirects=False)`; validation
  in `paginate()` before issuing redirected request); raise
  `GraphAPIError(error_code="invalid_redirect")` on rejection
  **Dependencies**: 9.1.5

- [ ] 9.1.7 Write tests for past/malformed Retry-After header
  (past HTTP-date falls through; malformed value logs warning and
  falls through; neither raises)
  **Spec scenarios**: graph-client / "Past HTTP-date Retry-After
  falls through to default backoff", "Malformed Retry-After is
  logged and ignored"
  **Design decisions**: D13
  **Dependencies**: 8.1.1

- [ ] 9.1.8 Extend Retry-After parsing in `GraphClient` to detect
  past HTTP-dates and malformed values; emit a structured warning
  with sanitized header value
  **Dependencies**: 9.1.7

- [ ] 9.1.9 Write test for the measurable msal concurrency
  scenario (mocked `acquire_token_silent` blocks 100ms; two
  concurrent extension calls complete within 250ms; an unrelated
  `asyncio.sleep(0)` yields within 10ms during the MSAL block)
  **Spec scenarios**: msal-auth / "Concurrent Graph calls are not
  serialized by MSAL"
  **Design decisions**: D20
  **Dependencies**: 1.5

### 9.2 wp-foundation additions (extension factory)

- [ ] 9.2.1 Write test for real factory called with `persona=None`
  raising actionable `TypeError` (each of `ms_graph`, `outlook`,
  `teams`, `sharepoint` factory; assertion on error message
  containing extension name + `extensions.<name>` + `auth.ms`)
  **Spec scenarios**: extension-registry / "Real factory called
  with persona=None raises actionable TypeError"
  **Design decisions**: D26
  **Dependencies**: 8.4.2

- [ ] 9.2.2 Implement the `persona is None` short-circuit at the
  top of each real extension's `create_extension` factory; raise
  `TypeError` with the contract-specified message before any
  MSALStrategy or GraphClient construction
  **Dependencies**: 9.2.1

### 9.3 wp-extensions additions (pagination discipline)

- [ ] 9.3.1 Write tests asserting list-tool pagination discipline
  (each list-tool's `get`/`post` call count is bounded by
  `ceil(items / page_size) + 1`, independent of item count;
  verified by mocking GraphClient and asserting call ledger)
  **Spec scenarios**: ms-extensions / "list_messages does not call
  Graph per item"
  **Dependencies**: 2.4, 3.5, 4.5, 5.4

- [ ] 9.3.2 Audit each list-tool implementation
  (`outlook.list_messages`, `teams.list_chats`,
  `sharepoint.list_documents`, `ms_graph.search_messages`) and
  remove any per-item Graph fetches; replace with `$expand` /
  `$select` where enrichment is required; document upper-bound on
  Graph API calls in each tool's docstring
  **Dependencies**: 9.3.1

- [ ] 9.3.3 Write tests for per-tool page_ceiling description
  presence (each list-tool's StructuredTool description contains
  `"page_ceiling"` followed by an integer; mismatch from
  GraphClient default visible)
  **Spec scenarios**: ms-extensions / "list_messages declares its
  page_ceiling in tool description"
  **Dependencies**: 2.4, 3.5, 4.5, 5.4

- [ ] 9.3.4 Update each list-tool's StructuredTool description to
  include effective `page_ceiling` and a note about
  truncation-via-error if results would exceed it
  **Dependencies**: 9.3.3

### 9.4 Cross-cutting plan-hygiene

- [ ] 9.4.1 Validate the pinned `agent-framework` version
  (`>=1.0.0,<2.0.0` per design D5) at implementation start. If
  Context7 reports an incompatible version at impl time, update
  the pin in `pyproject.toml` (task 1.16) and re-run uv lock as
  a single foundation-touching commit before merging.
  **Dependencies**: 1.16

- [ ] 9.4.2 Update task 8.1.5/8.1.6 cross-references: 8.1.5 is the
  GraphClient-side trace_graph_call test (graph-client spec); 9.1.1
  is the provider-side test (observability spec). Both test families
  must pass before wp-foundation merges. (Documentation only — no
  code change in this task.)
  **Dependencies**: 8.1.5, 9.1.1
