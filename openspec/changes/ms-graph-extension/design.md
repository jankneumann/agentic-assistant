## Context

Phase P5 lights up Microsoft 365 access for the agentic-assistant. With
foundations P3 (`http-tools-layer`), P1.8 (`capability-protocols`), and
P9 (`error-resilience`) all archived, the prerequisites for a real MS
Graph integration are in place. Today, the four target extensions are
11-line shims (`StubExtension`-returning factories) and the MS Agent
Framework harness raises `NotImplementedError`. The work persona — not
yet built — is the primary consumer; the personal persona will continue
to use Google Workspace (P14) for personal work.

The proposal selected **Approach A.2** (Transport-interface Protocol +
custom MS implementation). This document captures the technical
decisions that A.2 needs to land cleanly across one foundation
work-package, four extension work-packages, and one harness
work-package.

Discovery decisions already locked:

- **MSAL flow**: `acquire_token_interactive()` + `acquire_token_silent()`
  for delegated; `client_credentials` for unattended. Pluggable
  strategies. Device-code as headless fallback.
- **MSAF SDK**: confirmed via Context7 as `agent-framework` (PyPI
  package `agent-framework`, GitHub `microsoft/agent-framework`).
- **API surface**: read-heavy MVP + send Outlook email + post Teams
  chat. SharePoint write-side, calendar create, Teams meeting create
  deferred to P5b.
- **Test strategy**: `respx` + typed `MockGraphClient` + opt-in
  `RUN_GRAPH_TESTS=1` integration suite.
- **Persona default**: personal persona stays opted out (P5 ships code
  only).
- **Broker target**: web-interactive everywhere (no `msal[broker]`).

## Goals / Non-Goals

**Goals:**

- Deliver four real MS 365 extensions wired end-to-end through the
  existing capability resolver, tool policy, and resilience layers.
- Deliver a fully implemented `MSAgentFrameworkHarness` (replacing the
  `NotImplementedError` stub) using `agent-framework` as the SDK,
  satisfying `SdkHarnessAdapter`'s contract (create_agent, invoke,
  spawn_sub_agent).
- Establish reusable foundation modules (`core/cloud_client.py`,
  `core/msal_auth.py`, `core/graph_client.py`) so that P14
  google-extensions can either implement the same Protocol with custom
  code or with a vendor SDK adapter.
- Maintain zero regressions: existing `extension-registry`,
  `harness-adapter`, and `error-resilience` requirements that don't
  change MUST keep passing. Stub behavior for `gmail`/`gcal`/`gdrive`
  (P14 territory) is preserved verbatim.

**Non-Goals:**

- Personal persona enabling MS extensions in P5. (Deferred to P15
  `work-persona-config` for the work persona, never for personal.)
- Windows token broker (`msal[broker]` / PyWAM) integration.
- SharePoint writes, Outlook calendar event creation, Teams meeting
  creation/management.
- Wrapping or adopting `msgraph-sdk`. The Protocol shape allows a
  future drop-in adapter, but P5 ships custom httpx only.
- Cross-tenant or multi-account auth. One persona = one tenant + one
  identity.
- Performance optimization of paginated reads beyond what
  `@odata.nextLink` chasing naturally provides.

## Decisions

### D1 — Two pluggable MSAL strategies

The auth foundation exposes a `MSALStrategy` Protocol with a single
async method `acquire_token(scopes: list[str]) -> str`. Two concrete
implementations land in P5:

- **`InteractiveDelegatedStrategy`** — uses
  `msal.PublicClientApplication` with `acquire_token_interactive()` for
  first-run consent (opens system browser; honors Entra ID SSO,
  conditional access, MFA). On subsequent calls, prefers
  `acquire_token_silent()` from a serialized token cache. If silent
  acquisition fails (e.g., refresh token expired), falls back to
  interactive.
- **`ClientCredentialsStrategy`** — uses
  `msal.ConfidentialClientApplication.acquire_token_for_client()` with
  `tenant_id`, `client_id`, `client_secret`. No user identity, no
  refresh token, no cache. Token TTL is the only state.

Selection is persona-driven via `auth.flow:
interactive | client_credentials` in `persona.yaml`. The factory
`create_msal_strategy(persona)` returns the appropriate instance.

**Why two strategies, not one:** The work persona's day-to-day usage
needs delegated identity (the agent acts "as the user" — sending mail
as them, reading their inbox). But P7 scheduler, P6 a2a-server, and P17
mcp-server-exposure will need unattended auth for jobs that act without
a user present. Both flows are first-class in Entra ID, and bundling
them in one strategy class would couple unrelated configuration paths.

**Alternatives considered:**

- *Single unified strategy with a flow enum*: rejected because the
  initialization parameters differ enough that the class would be a
  switchboard with mostly-disjoint code paths.
- *Device code as a strategy class*: rejected because device code is a
  fallback-when-headless concern, not a deployment target. Operators
  who need it set `MSAL_FALLBACK_DEVICE_CODE=1`, which the
  `InteractiveDelegatedStrategy` honors at runtime by switching
  `acquire_token_interactive()` to `initiate_device_flow()`.

### D2 — Per-persona token cache file with restrictive permissions

Token cache lives at
`personas/<persona_name>/.cache/msal_token_cache.json`. The directory
is created on first run with mode `0o700`; the file is written with
mode `0o600`. The cache uses MSAL's `SerializableTokenCache`
(documented round-tripping API).

Atomicity: writes go to `msal_token_cache.json.tmp` then `os.rename()`
onto the final path. On read, missing-file is silently treated as
"empty cache" so first runs don't error.

**Why per-persona, not per-account:** The persona is the auth boundary
in this project (CLAUDE.md "Persona = execution boundary"). Two
personas share zero auth state.

**Why JSON cache and not OS keychain:** `msal[broker]` and OS-keychain
integration are deferred (Q6 broker decision). JSON in
`personas/<name>/.cache/` is gitignore-able by the persona submodule
template. P5 amends `personas/_template/.gitignore` to exclude
`.cache/` so it's never committed by accident.

**Alternatives considered:**

- *Single global cache at `~/.cache/agentic-assistant/`*: rejected
  because it crosses persona boundaries (a `personal`-tenant token
  could end up readable to a `work` persona session).
- *No cache (re-auth every run)*: rejected because interactive flows
  would prompt every CLI invocation — unusable.

### D3 — `CloudGraphClient` Protocol shape

A new module `core/cloud_client.py` declares:

```python
@runtime_checkable
class CloudGraphClient(Protocol):
    """Transport-level interface for cloud-graph-shaped APIs."""

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...

    async def paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def health_check(self) -> HealthStatus: ...
```

`paginate` chases `@odata.nextLink` by default; for Google APIs (P14)
the same Protocol can chase `nextPageToken` in its concrete
implementation — neither convention bleeds through the Protocol.

**Why exactly these four methods:** They cover 100% of the call shapes
the four MS extensions need: list (`get` + `paginate`), read (`get`),
write (`post`), and report-self-health (`health_check`). PUT/PATCH/DELETE
are deferred to P5b.

**Alternatives considered:**

- *Expose the underlying httpx Client directly*: rejected because that
  binds extensions to httpx and makes a future SDK swap leak.
- *Generate the Protocol from OpenAPI*: rejected because Graph's
  OpenAPI is enormous and the project already chose hand-curated
  scopes.

### D4 — `GraphClient` implementation = httpx + MSAL strategy + resilience

`core/graph_client.py` provides `GraphClient` — the custom MS
implementation of `CloudGraphClient`. Key properties:

- **Single shared `httpx.AsyncClient`** per persona (lifespan-managed
  through the P10 extension lifecycle when that lands; P5 builds with
  a context-manager pattern in the meantime).
- **MSAL token plumbing**: every request fetches a fresh token via the
  configured strategy's `acquire_token(scopes)`. Token caching is the
  strategy's responsibility, not the client's.
- **Resilience integration**: every method wraps with
  `@resilient_http(breaker_key=f"graph:{extension_name}")` from P9.
  Breaker keys are namespaced per extension so one extension's
  unavailability doesn't trip another's calls. The `extension_name` is
  passed at `GraphClient` construction.
- **`paginate()` semantics**: yields each page's `value` array as a
  whole list, not individual records. Caller decides whether to
  flatten. Hard ceiling at 100 pages (configurable via constructor
  arg) to prevent runaway loops.
- **Error sanitization**: on any non-2xx, raises a custom
  `GraphAPIError` whose `__str__` is run through `_sanitize_error_string`
  (P9) so logged errors never contain access tokens.

**Why pass `extension_name` at construction:** Each extension owns
its own `GraphClient` instance, scoped to its own breaker key. This
lets observability dashboards (P4) attribute Graph failures to the
right extension, and lets a flapping extension's circuit open
without cascading.

### D5 — MSAF SDK is `agent-framework`; harness uses `OpenAIChatClient`

Per Context7 confirmation: `agent-framework` (PyPI: `agent-framework`,
repo: `github.com/microsoft/agent-framework`) is the canonical
"Microsoft Agent Framework" Python package. The `MSAgentFrameworkHarness`
will use:

- `from agent_framework import Agent, ai_function`
- `from agent_framework.openai import OpenAIChatClient` (when persona
  uses OpenAI directly) or
  `from agent_framework.azure_openai import AzureOpenAIChatClient`
  (when persona uses Azure OpenAI)
- Construction: `Agent(client=chat_client, instructions=composed_prompt,
  tools=converted_tool_list)`
- Invocation: `await agent.run(message)` returns the final response.
  The harness extracts the response string and returns it from
  `invoke()`.

**Tool conversion is the central novelty** of this harness. Our
extensions emit tools via two methods today: `as_langchain_tools()`
returns LangChain `StructuredTool` instances; `as_ms_agent_tools()`
already exists in the Extension Protocol (extension-registry spec) but
was never populated. P5 populates it: each extension's
`as_ms_agent_tools()` returns a list of `agent-framework`-compatible
async functions (decorated with `@ai_function` from
`agent_framework`). The MSAF harness consumes ONLY
`as_ms_agent_tools()`, never `as_langchain_tools()`. Conversely, the
DeepAgents harness consumes only `as_langchain_tools()`. The two tool
formats are siblings, not derived from one another, because the
function-signature semantics differ enough that adapting after the
fact is more brittle than authoring twice.

**Sub-agent spawning**: `agent-framework` supports tool-as-agent
patterns (one agent's `tools` list can include another agent's `run`
method). `spawn_sub_agent(role, task, tools, extensions)` builds a
nested `Agent` for the sub-role and calls `await sub_agent.run(task)`
synchronously, returning the result string. This mirrors how
`DeepAgentsHarness` does it.

**Alternatives considered:**

- *`semantic-kernel` Python*: rejected because it's broader than we
  need and its agent abstractions are layered on top of more
  abstractions (kernel, plugins, planners). MSAF's flat shape fits the
  HarnessAdapter contract more directly.
- *`microsoft/agents-for-python` (M365 Agents SDK)*: rejected because
  it's targeted at building bots that run inside Teams/Copilot Studio,
  not at building local agents that consume MS Graph data.

### D6 — Extension internal structure

Each extension module follows this shape:

```python
# src/assistant/extensions/outlook.py

class OutlookExtension:
    name: str = "outlook"

    def __init__(self, config: dict[str, Any], client: GraphClient) -> None:
        self.config = config
        self.scopes = list(config.get("scopes", DEFAULT_SCOPES) or [])
        self._client = client
        self._breaker = CircuitBreakerRegistry.get_breaker(f"extension:{self.name}")

    def as_langchain_tools(self) -> list[StructuredTool]:
        return [
            _build_langchain_tool("outlook.list_messages", self._list_messages),
            _build_langchain_tool("outlook.read_message", self._read_message),
            # ... etc
        ]

    def as_ms_agent_tools(self) -> list[Callable]:
        return [
            ai_function(name="outlook.list_messages")(self._list_messages),
            ai_function(name="outlook.read_message")(self._read_message),
            # ... etc
        ]

    async def health_check(self) -> HealthStatus:
        return health_status_from_breaker(self._breaker, key=f"extension:{self.name}")

    async def _list_messages(self, top: int = 25, ...) -> list[dict]: ...
    async def _read_message(self, message_id: str) -> dict: ...
```

Key points:

- The same private async method (`_list_messages`) is wrapped twice —
  once for LangChain, once for MSAF — preserving identical behavior at
  the wire level.
- `GraphClient` is **injected** at construction, not built inside the
  extension. This makes testing trivial (`MockGraphClient` substitutes
  cleanly) and keeps each extension stateless about transport.
- Default scopes per extension are declared as module-level constants,
  overridable from `persona.yaml`'s `extensions.<name>.config.scopes`.

### D7 — Test infrastructure

Three layers of testing:

1. **Unit tests with `respx`** — mock httpx at the wire level. Each
   extension test file (`tests/test_extensions_outlook.py` etc.)
   loads a fixture JSON (`tests/fixtures/graph_responses/outlook/
   list_messages.json`), pins respx routes, invokes the extension's
   tool, asserts the parsed result.
2. **Extension-level tests with `MockGraphClient`** — substitute the
   `CloudGraphClient` Protocol entirely. These tests verify extension
   behavior without HTTP at all: pagination handling, error mapping,
   scope assembly. `tests/mocks/graph_client.py` exposes
   `MockGraphClient` with method-level patch hooks.
3. **Opt-in integration tests** — gated on `RUN_GRAPH_TESTS=1` in env.
   These exercise real MSAL device-code auth + real Graph endpoints
   in a `tests/integration/` directory not collected by default. They
   require `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and a valid
   refresh-token-bearing test account. CI does NOT run these.

**Privacy boundary preservation:** All test fixtures live under
`tests/fixtures/graph_responses/`. None contain real names, real email
addresses, or real chat content. Each fixture has a leading sentinel
comment `// FIXTURE_GRAPH_RESPONSE_v1` to satisfy the existing privacy
guard pattern (CLAUDE.md G6).

**MockGraphClient typing:** Implements `CloudGraphClient` Protocol
exactly. Stub return values are configured per-test via simple
attribute assignment (`mock.next_get_response = {...}`). No global
state.

### D8 — Persona auth schema (work persona, future)

The work persona's `personas/work/persona.yaml` (lands in P15) will
declare:

```yaml
auth:
  ms:
    flow: interactive  # or "client_credentials"
    tenant_id_env: AZURE_TENANT_ID
    client_id_env: AZURE_CLIENT_ID
    # for client_credentials only:
    client_secret_env: AZURE_CLIENT_SECRET
    # cache location relative to persona root:
    token_cache_path: ".cache/msal_token_cache.json"

extensions:
  ms_graph:
    enabled: true
    config:
      scopes: ["User.Read", "People.Read"]
  outlook:
    enabled: true
    config:
      scopes: ["Mail.Read", "Mail.Send", "Calendars.Read"]
  teams:
    enabled: true
    config:
      scopes: ["Chat.Read", "Chat.ReadWrite", "ChannelMessage.Read.All"]
  sharepoint:
    enabled: true
    config:
      scopes: ["Sites.Read.All", "Files.Read.All"]
```

The `_env(NAME)` lookup pattern from `core/persona.py` resolves these
to actual values at config-load time. P5 documents this schema in
`docs/perso na-auth-schema.md` (or extends an existing doc) so P15 can
copy it. P5 itself ships ZERO persona YAML changes.

### D9 — Error handling boundaries

Three error layers, each with a clear contract:

| Layer | Errors raised | Sanitization |
|---|---|---|
| `MSALStrategy` | `MSALAuthenticationError` (custom) | error message scrubbed of token/secret traces by inheritance from `_sanitize_error_string` |
| `GraphClient` | `GraphAPIError` with `status_code`, `error_code`, `request_id` | sanitized `__str__`; never includes Authorization header |
| Extension tool | propagates `GraphAPIError` upward; wraps unexpected Python errors as `ExtensionError` | extension name prepended to error message |

The circuit breaker (P9) sits inside `GraphClient` via `@resilient_http`,
so transient errors retry-then-trip transparently. Authentication
errors (`MSALAuthenticationError`) **do not** retry — they propagate
immediately, because re-trying with the same expired token is
pointless. The extension's `health_check()` reports
`HealthState.UNAVAILABLE` when its breaker is OPEN, and
`HealthState.DEGRADED` when half-open.

### D10 — Capability resolver wiring for MSAF

The MSAF harness consumes the following capabilities via the
`CapabilityResolver` (P1.8):

- **`ToolPolicy`**: returns the role's allowed extensions; harness
  calls `as_ms_agent_tools()` on each authorized extension and feeds
  the union into `Agent(tools=...)`.
- **`ContextProvider`**: returns the composed system prompt; harness
  passes as `Agent(instructions=...)`.
- **`GuardrailProvider`**: invoked by the harness's `spawn_sub_agent`
  to gate delegation requests, mirroring DeepAgents' integration.
- **`MemoryPolicy`**: not consumed in P5. The MSAF SDK does not yet
  have a clean memory injection point that maps to our
  `MemoryPolicy.export_for_harness()`. Memory wiring is deferred to a
  P5b follow-up after the MSAF SDK exposes a stable memory hook.
- **`SandboxProvider`**: not consumed. Sandbox semantics apply to host
  harnesses (Claude Code), not SDK harnesses.

**Why MemoryPolicy is deferred, not minimally wired:** Bolting memory
on with brittle prompt injection now would either lock us into a
contract `agent-framework` doesn't yet support, or paper over the
Memory contract entirely. Better to ship MSAF without memory in P5
and add a follow-up issue.

### D11 — Extension tool format conversion is per-extension, not central

Each extension authors its tools twice (once as LangChain
`StructuredTool` for DeepAgents, once as `@ai_function`-decorated async
methods for MSAF). The extension's `_list_messages` private method is
the canonical implementation; both wrappers call it.

**Why not a central converter:** A converter that translates
`StructuredTool → ai_function` (or vice versa) has to introspect
LangChain's `args_schema` (Pydantic BaseModel) and re-emit it as
`Annotated[..., Field(description=...)]` parameter declarations. Doing
this generically requires reflection that hides parameter docs and
makes tool descriptions less precise. Authoring twice is ~20 lines per
tool and produces clearer tool descriptions in both ecosystems.

### D12 — Module boundaries summary

```
src/assistant/core/
  cloud_client.py         (NEW: CloudGraphClient Protocol)
  msal_auth.py            (NEW: MSALStrategy + 2 concrete strategies)
  graph_client.py         (NEW: GraphClient = httpx impl of Protocol)
  resilience.py           (UNCHANGED: P9)
  persona.py              (UNCHANGED: _env() pattern)

src/assistant/extensions/
  base.py                 (UNCHANGED: Extension Protocol)
  _stub.py                (UNCHANGED: StubExtension for gmail/gcal/gdrive)
  ms_graph.py             (REPLACE: real impl)
  outlook.py              (REPLACE: real impl)
  teams.py                (REPLACE: real impl)
  sharepoint.py           (REPLACE: real impl)
  gmail.py                (UNCHANGED: stays stub until P14)
  gcal.py                 (UNCHANGED: stays stub until P14)
  gdrive.py               (UNCHANGED: stays stub until P14)

src/assistant/harnesses/
  base.py                 (UNCHANGED: SdkHarnessAdapter ABC)
  factory.py              (UNCHANGED: registry already lists MSAF)
  sdk/
    deep_agents.py        (UNCHANGED: P1)
    ms_agent_fw.py        (REPLACE: full impl)

tests/
  mocks/graph_client.py   (NEW)
  fixtures/graph_responses/* (NEW per-endpoint JSON)
  test_msal_auth.py       (NEW)
  test_graph_client.py    (NEW)
  test_extensions_ms_graph.py (NEW)
  test_extensions_outlook.py  (NEW)
  test_extensions_teams.py    (NEW)
  test_extensions_sharepoint.py (NEW)
  test_harness_ms_agent_fw.py (NEW)
  integration/test_graph_smoke.py (NEW; opt-in)
```

## Risks / Trade-offs

- **[Risk] `agent-framework` SDK churn** → P5 adopts a new-ish SDK
  that may have breaking changes between versions. **Mitigation**: pin
  to a tested version in `pyproject.toml`; add an integration test that
  exercises the harness's basic invoke flow and runs in CI; document
  the version in `design.md`'s D5 section so future churn is traceable.
- **[Risk] MSAL refresh token expiry mid-session** → If a refresh
  token expires during a long-running agent invocation, the next
  Graph call will 401. **Mitigation**: `GraphClient` catches 401 +
  `WWW-Authenticate: Bearer error="invalid_token"`, calls the
  strategy's `acquire_token()` with `force_refresh=True`, retries
  once. If that fails, propagates `MSALAuthenticationError` — agent
  surfaces as "authentication required, please re-run" message.
- **[Risk] Conditional access policies block headless flows** → Some
  Entra ID tenants require device compliance / location checks that
  fail in CI. **Mitigation**: integration tests are explicitly
  opt-in (`RUN_GRAPH_TESTS=1`) and gated to a dedicated CI account
  whose conditional access policies are relaxed. CI never runs them.
- **[Risk] Tool-format duplication drift** → If an extension author
  updates `as_langchain_tools()` but forgets `as_ms_agent_tools()`,
  one harness sees stale tools. **Mitigation**: a
  `tests/test_extensions_dual_format.py` parameterized test asserts
  the two methods return the same number of tools with the same names
  for each extension.
- **[Risk] Token cache file written to a world-readable persona dir
  by accident** → `personas/<name>/.cache/` could be gitignored
  inconsistently. **Mitigation**: P5 amends
  `personas/_template/.gitignore` to add `.cache/` and adds a
  startup check that asserts `os.stat(cache_dir).st_mode & 0o077 ==
  0` (no group/other access) before writing.
- **[Risk] `msgraph-sdk` adapter never gets written, Protocol becomes
  dead weight** → If P14 also chooses custom httpx, the
  `CloudGraphClient` Protocol is unused abstraction. **Mitigation**:
  the Protocol is small (~5 methods) and exists to encode the
  *shape* of any cloud-graph backend. Even with two custom
  implementations, the Protocol still serves as a documented
  contract for tests and is no more than 30 lines of code.
- **[Trade-off] No memory in MSAF harness in P5** → MSAF agents
  cannot consult per-persona memory in P5. **Acceptance**:
  documented as a follow-up; DeepAgents already covers
  memory-aware workflows for the personal persona, and the work
  persona launches first without memory anyway (P2 delivered the
  layer but no persona has yet wired it).

## Migration Plan

P5 is a pure-additive change for the four extensions and the MSAF
harness — no production data exists yet to migrate. The deployment
plan reduces to:

1. **Land foundation**: merge `wp-foundation` (cloud_client +
   msal_auth + graph_client) ahead of the four extension packages. All
   four extensions depend on it.
2. **Land four extension packages in parallel**: `wp-ms-graph`,
   `wp-outlook`, `wp-teams`, `wp-sharepoint`. Each can merge
   independently because their write_allow scopes are disjoint.
3. **Land MSAF harness package**: `wp-msaf-harness` depends only on
   `wp-foundation` (it does NOT depend on the four extension packages —
   the harness consumes whatever extensions are enabled, but doesn't
   import from them at module-load time).
4. **Land integration package**: `wp-integration` runs the full test
   suite, validates `openspec --strict`, and confirms the four
   extensions and harness all coexist cleanly.
5. **No persona YAML changes in P5**. The personal persona keeps MS
   extensions disabled. The work persona will turn them on in P15.

**Rollback**: If P5 ships and turns out to break the personal persona
somehow, `git revert` the merge commit. Because no persona consumes
the new code at the time of merge, rollback has zero data impact —
only code regression.

## Open Questions

- **`agent-framework` version pin**: which exact version? Decision
  deferred to `wp-foundation` task 1.1, where Context7 will be queried
  again for the current stable version at implementation time.
- **MSAF chat client choice**: `OpenAIChatClient` vs.
  `AzureOpenAIChatClient` is persona-driven. P5 supports both but only
  exercises one in the integration test. Which one CI exercises is
  decided at integration-test authoring time based on which credential
  set the CI account has.
- **`spawn_sub_agent` cycle detection**: P12 `delegation-context` is
  the phase that adds delegation-chain cycle detection. P5's MSAF
  harness implements `spawn_sub_agent` without cycle detection (same
  as DeepAgents' P1 implementation). Cycle detection is a P12
  concern.
- **Document the Approach A.3 retrofit cost**: If P14
  google-extensions chooses to wrap `google-api-python-client`,
  should we also retroactively wrap `msgraph-sdk` for symmetry? This
  is an architectural question that surfaces only after P14 ships.
  Captured as a P14 design.md open question, not a P5 concern.
