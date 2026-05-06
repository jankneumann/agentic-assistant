## Why

Phase P5 of the agentic-assistant roadmap (`openspec/roadmap.md`) is the
last remaining "tools-not-yet-real" gap before the assistant can act on
work-account data. Today, `src/assistant/extensions/{ms_graph,teams,
sharepoint,outlook}.py` are 11-line shims returning `StubExtension`
with empty `as_langchain_tools()` and `as_ms_agent_tools()`, and
`src/assistant/harnesses/sdk/ms_agent_fw.py` raises
`NotImplementedError`. With P3 `http-tools-layer`, P1.8
`capability-protocols`, and P9 `error-resilience` all archived, every
foundation piece a real Microsoft 365 integration depends on is now
available. P5 fills in the bodies.

Driving constraint: the work persona is the **primary** consumer.
Auth must support **Entra ID + SSO** as a first-class path, not as an
afterthought. Personal MS account access is **secondary** — the
personal persona will continue to use Google Workspace (P14) for
day-to-day personal work.

## What Changes

- **Add** `core/msal_auth.py` with two pluggable MSAL strategies:
  - `InteractiveDelegatedStrategy` — `acquire_token_interactive()`
    first run + `acquire_token_silent()` thereafter, honoring
    Entra ID SSO / MFA / conditional access via the system browser.
    Refresh tokens cached via MSAL `SerializableTokenCache` to
    `personas/<name>/.cache/msal_token_cache.json`.
  - `ClientCredentialsStrategy` — service-principal token acquisition
    for unattended jobs (P7 scheduler, P6 A2A server, P17 MCP server).
  - Strategy selection driven by persona YAML (`auth.flow:
    interactive | client_credentials`).
  - Device-code flow available as a documented headless fallback
    (no first-class strategy class — operators set
    `MSAL_FALLBACK_DEVICE_CODE=1`).
- **Add** `core/graph_client.py` — typed httpx wrapper for
  `https://graph.microsoft.com/v1.0/`, with:
  - MSAL strategy plumbing (bearer token from active strategy).
  - `@odata.nextLink` pagination via `paginate()` helper.
  - Wrapped with `@resilient_http(breaker_key="graph:<extension>")`
    from P9.
  - Sanitized error logging (no token bleed; piggybacks on P9's
    `_sanitize_error_string`).
- **Replace** the four extension stubs with real implementations,
  each emitting LangChain-compatible tools via `as_langchain_tools()`
  and MSAF-compatible tools via `as_ms_agent_tools()`:
  - `ms_graph` — generic Graph tools: `search_people`,
    `get_my_profile`, `search_messages` (cross-mailbox).
  - `outlook` — `list_messages`, `read_message`, `search_messages`
    (mailbox-scoped), **`send_email` (write)**, `list_calendar_events`,
    `find_free_times`.
  - `teams` — `list_chats`, `list_channel_messages`, `read_message`,
    **`post_chat_message` (write)**.
  - `sharepoint` — `search_sites`, `list_documents`,
    `download_document` (read-only; SharePoint writes deferred to
    P5b follow-up).
- **Replace** the `MSAgentFrameworkHarness` `NotImplementedError`
  stub with a full `SdkHarnessAdapter` implementation, mirroring the
  shape of `harnesses/sdk/deep_agents.py`. SDK choice (e.g.,
  `agent-framework`, `semantic-kernel`, `azure-ai-agents`) confirmed
  via Context7 in `design.md`.
- **Update** all four extensions to return `HealthStatus` from
  `health_check()` per the post-P9 protocol (gotcha G9).
- **Add** test infrastructure: `tests/fixtures/graph_responses/`,
  a typed `MockGraphClient` under `tests/mocks/`, and `respx`-based
  unit tests per extension. Optional integration suite under
  `RUN_GRAPH_TESTS=1` for opt-in real-Graph smoke checks.
- **Personal persona unchanged**: `personas/personal/persona.yaml`
  does NOT enable any of the four extensions. P5 ships extensions as
  code only — P15 `work-persona-config` is where they get turned on
  for the work persona.
- **No protocol changes**: `Extension`, `HarnessAdapter`,
  `SdkHarnessAdapter` shapes are already correct. P5 fills bodies
  only.

## Capabilities

### New Capabilities

- `msal-auth`: MSAL strategy abstraction for delegated (interactive +
  silent) and unattended (client credentials) flows; serializable
  token cache contract; persona-driven strategy selection.
- `graph-client`: Typed httpx wrapper for Microsoft Graph API with
  pagination, resilience integration, and MSAL token plumbing.
  Reusable foundation for all four extensions and the MSAF harness.
- `ms-extensions`: The four real Microsoft 365 extensions
  (`ms_graph`, `outlook`, `teams`, `sharepoint`) with their
  per-extension Graph scopes, tool sets, and health checks.
  Read-heavy MVP plus narrow writes (Outlook send-email + Teams
  post-chat).
- `ms-agent-framework-harness`: Full `SdkHarnessAdapter`
  implementation for the MS Agent Framework Python SDK, replacing
  the registered-but-stubbed placeholder.

### Modified Capabilities

- `extension-registry`: Stub-factory references for `ms_graph`,
  `teams`, `sharepoint`, `outlook` are upgraded from
  `StubExtension`-returning to real implementation modules. Any
  scenarios asserting "stubs return empty tool lists" become MODIFIED
  to assert "real implementations return non-empty lists when persona
  enables them". Confirmed during specs generation.
- `harness-adapter`: `MSAgentFrameworkHarness` is upgraded from
  registered-but-stubbed to fully-implemented. Any scenarios
  asserting `NotImplementedError` raise become MODIFIED.

## Approaches Considered

### Approach A — Layered foundation (msal-auth + graph-client + extensions) — **Recommended**

Build an explicit two-tier foundation: `core/msal_auth.py` exposes
strategy classes, `core/graph_client.py` exposes a typed httpx
wrapper that consumes a strategy. Each extension owns ~150-300 lines
of domain-specific tool wrappers using the shared `GraphClient`.
The MSAF harness consumes the same `GraphClient` plus the persona's
strategy, wired through the P1.8 capability resolver.

**Pros:**
- Single auth + transport implementation; one place to tune retry,
  pagination, and token plumbing.
- Mirrors project conventions (`core/resilience.py`, `core/memory.py`,
  `http_tools/builder.py` all follow the "shared core + thin per-domain
  module" pattern).
- Extensions are independently testable against `MockGraphClient`.
- Foundation work-package (a) blocks but is small (~600 LOC); the
  four extension packages then parallelize cleanly across vendors.
- `msal-auth` and `graph-client` become reusable for P14
  google-extensions (similar OAuth + httpx + pagination shape) and
  P6 a2a-server (delegated identity propagation).

**Cons:**
- Foundation must land before any extension; ~1 day of serial work
  before parallelism kicks in.
- One more abstraction layer than strictly needed for "just MS
  Graph" — but justified by P14 and beyond.

**Effort:** L (largest scope, but with parallel fan-out after foundation)

### Approach B — Per-extension self-contained

Each extension owns its own MSAL flow, httpx client, retry wrapping,
and pagination logic. No shared `core/msal_auth.py` or
`core/graph_client.py`.

**Pros:**
- Pure parallelism from day one — no foundation gate.
- Each extension is self-contained; refactoring one doesn't risk the
  others.

**Cons:**
- ~4× duplication of MSAL setup, token cache wiring, retry
  configuration, pagination logic.
- Four separate token caches mean the user authenticates once per
  extension (4× device-code prompts on first run).
- Cross-extension auth coordination (e.g., one Entra app registration,
  one consent flow covering all four) becomes hard to enforce.
- P14 google-extensions would need a parallel duplication exercise
  with no shared scaffold.

**Effort:** M (per-extension), but L overall once duplication is summed

### Approach C — Wrap Microsoft's official `msgraph-sdk`

Use `msgraph-sdk` (PyPI, MS-supported) instead of building a custom
`graph_client.py`. Thin-wrap the SDK to satisfy our `Extension`
protocol; auth via `azure-identity` rather than direct MSAL.

**Pros:**
- Less code to maintain; MS handles new endpoints, schema updates,
  and Graph API version upgrades.
- Typed Python models for every Graph entity (auto-generated from
  Kiota).

**Cons:**
- Heavyweight dep tree (`msgraph-sdk` pulls Kiota runtime,
  `azure-identity`, `azure-core`, etc.) — adds ~50 MB to the install.
- Less control over the resilience layer — `msgraph-sdk` has its own
  retry middleware that doesn't compose naturally with our
  `@resilient_http` + `CircuitBreakerRegistry`. Either we accept
  duplicate retry layers or we fight the SDK.
- Opinionated about auth: prefers `azure-identity` over direct MSAL,
  which clashes with the project's `_env()`-based persona credential
  pattern.
- Less reusable for P14 google-extensions — Google's SDKs follow a
  different shape, so we'd diverge instead of converge.

**Effort:** M (less code, but more friction at integration boundaries)

### Recommendation

Approach **A** (Layered foundation). It aligns with established
project conventions, produces reusable scaffolding for P14 and P6,
keeps the resilience integration clean, and trades a small upfront
serial cost (foundation work-package) for clean parallelism across
the four extensions and the MSAF harness afterward.

## Impact

**New code:**
- `src/assistant/core/msal_auth.py` (~300 LOC)
- `src/assistant/core/graph_client.py` (~400 LOC including
  pagination + resilience integration)
- `src/assistant/extensions/ms_graph.py` — replaces 11-line stub
  (~250 LOC)
- `src/assistant/extensions/outlook.py` — replaces 11-line stub
  (~350 LOC including send-email writer)
- `src/assistant/extensions/teams.py` — replaces 11-line stub
  (~300 LOC including post-chat writer)
- `src/assistant/extensions/sharepoint.py` — replaces 11-line stub
  (~250 LOC, read-only)
- `src/assistant/harnesses/sdk/ms_agent_fw.py` — replaces 1.1K
  stub (~500 LOC; exact size depends on Context7-confirmed SDK)

**New test code:**
- `tests/mocks/graph_client.py` — typed `MockGraphClient`
- `tests/fixtures/graph_responses/` — JSON fixtures per Graph endpoint
- `tests/test_msal_auth.py`, `tests/test_graph_client.py`,
  `tests/test_extensions_ms_graph.py`, `tests/test_extensions_outlook.py`,
  `tests/test_extensions_teams.py`, `tests/test_extensions_sharepoint.py`,
  `tests/test_harness_ms_agent_fw.py`
- Optional `tests/integration/test_graph_smoke.py` (gated on
  `RUN_GRAPH_TESTS=1`)

**Modified code:**
- `src/assistant/extensions/_stub.py` — unchanged
- `src/assistant/harnesses/factory.py` — no signature change; the
  registry already lists `MSAgentFrameworkHarness`
- `pyproject.toml` — add `msal>=1.28`, `httpx>=0.27` (already present
  via P3), and the SDK chosen for MSAF (TBD via Context7)
- `personas/personal/persona.yaml` — **no change** (extensions stay
  opted out)

**Affected specs:** `extension-registry` (deltas), `harness-adapter`
(deltas), four new spec files under `specs/` (msal-auth,
graph-client, ms-extensions, ms-agent-framework-harness).

**Documentation:**
- `docs/gotchas.md` — add G10 entry on MSAL token cache file path
  + persona scoping if any non-obvious traps surface during
  implementation.
- `openspec/roadmap.md` — flip P5 from `pending` → `archived` on
  archival, plus a hygiene fix for P4 observability (currently lists
  `pending` but is archived as `2026-05-03-observability`).

**Dependencies:**
- New: `msal>=1.28` (or current stable; Context7 lookup will
  confirm; broker variant `msal[broker]` is **not** added — web
  interactive only per discovery decision Q6).
- New: `respx>=0.21` (test-only) for httpx mocking.
- New: MSAF SDK package — TBD via Context7 in `design.md`.

**Out of scope (deferred to P5b or later):**
- SharePoint writes (list-item create/update, doc upload).
- Outlook calendar event creation, accept/decline meeting invites.
- Teams meeting creation, channel/team management.
- `msal[broker]` (PyWAM) Windows broker integration.
- Personal persona enabling any MS extension.
- Cross-tenant / multi-account scenarios.

## Selected Approach

**A.2 — Transport-interface Protocol with custom MS implementation.**

Rationale: P5 ships custom code aligned with project conventions
(`httpx` + MSAL + P9 resilience), wrapped in a `CloudGraphClient`
Protocol that lets P14 google-extensions choose freely between
custom and SDK-wrapped backends without touching extension code.

Concrete shape:

- `core/cloud_client.py` — `CloudGraphClient` Protocol (~5
  methods: `get`, `post`, `paginate`, `get_token`, etc.)
- `core/msal_auth.py` — custom MSAL strategy classes (interactive
  + silent for delegated; client_credentials for unattended)
- `core/graph_client.py` — custom httpx implementation of
  `CloudGraphClient`, integrated with P9 `@resilient_http` and the
  selected MSAL strategy
- The four extensions consume `CloudGraphClient` through the
  Protocol, NOT the concrete `GraphClient` class — so a future
  `MsgraphSdkGraphClient` adapter (if ever needed) is a drop-in
  replacement at extension-build time.

Vendor-SDK clarification (for design.md context):

- `msgraph-sdk` (PyPI) and `msgraph-sdk-python` (GitHub) are the
  same project. The deprecated `msgraph-core` package is NOT used.
- If a future phase swaps to `msgraph-sdk`, the auth bridge is
  thin (replace `core/msal_auth.py` with `azure-identity`
  credentials), but the resilience and test costs noted in
  Approach C remain. P5 does not commit to that swap.

Approaches A.1 (no Protocol) and A.3 (wrap msgraph-sdk now) were
considered and rejected for the reasons above. A.3 may be
revisited in P14 if Google-side SDK experience suggests
SDK-wrapping is the better long-term shape for both clouds.
