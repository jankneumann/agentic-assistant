# Interface Stability Ledger

This document records the current stability classification of every
repo-owned interface enumerated in
[`primitives-and-providers.md`](./primitives-and-providers.md). It is the
discipline that turns the SPI claim from aspiration into a verifiable
promise: every interface in the table below has a named contract surface,
a stability level, a conformance test path (or a "not yet" placeholder),
and a list of known leaks or open design questions.

The ledger changes more often than the primitives document. Treat
`primitives-and-providers.md` as the **architecture** statement (what
exists, why) and this document as the **status** statement (what's
solid, what's drifting, what's open).

## Baseline reconciliation (2026-07-22)

This ledger was first written ~2026-05-16 and then stranded for two
months when a revert removed it from the tree. It has been reconciled
against everything that landed since (P5 through P30). Material state
changes folded in:

- **`Extension` protocol** — the `as_langchain_tools()` /
  `as_ms_agent_tools()` dual surface (the ledger's flagship "leaked
  interface" example) was **removed** in P17 `mcp-server-exposure` and
  replaced with `tool_specs() -> list[ToolSpec]`. The leak is resolved,
  not pending.
- **`MemoryManager` persona parameter** — no longer "a relic to drop
  in binding-manifest." Methods now take `persona: str | None`, the
  manager can be **bound at construction** (`persona_name`), and it
  **raises on a persona mismatch** rather than silently honouring
  either side.
- **`HarnessAdapter`** — streaming is realized (`astream_invoke ->
  AsyncIterator[HarnessEvent]`, P14a); `spawn_sub_agent` gained the
  additive `context: DelegationContext | None` parameter (P12); MSAF is
  a real provider, not a stub (P5).
- **`ModelProvider` / `ModelRef`** — a new realized interface (P19
  `model-provider-routing`, seam #6 in P24) that did not exist when the
  ledger was written. New entry below.
- **`SessionStore`** — durable sessions landed (P30 `durable-sessions`
  + the P24 checkpointer contract). Promoted off Pre-interface.

Entries left intentionally untouched (still accurate as
Pre-interface/proposed): `CapabilityRegistry`, `IdentityProvider`,
`Sandbox`, `AgentRegistry`, `SkillResolver`. Their open questions are
unchanged; only `CredentialProvider` progress (P13/P24/P25) is noted
inline under `IdentityProvider`.

## Stability levels

| Level | Meaning | When to use it | When to graduate |
|---|---|---|---|
| **Stable** | Interface is well-shaped; ≥2 providers implement it; conformance suite exists and is green; breaking changes require a deprecation cycle | A primitive has matured through real cross-provider use without churn | After two consecutive minor releases without interface-breaking changes |
| **Provisional** | Interface exists in code; ≥1 provider implements it; conformance suite exists or is being written; breaking changes are still allowed with a clear note | A primitive has been lifted into the repo but the shape is still settling | Promote to Stable after a second provider lands and the conformance suite catches the divergence |
| **Experimental** | Interface is being designed in code; expect changes per release; no conformance suite yet; consumers must accept the churn | A primitive is being built; the shape is forming through use | Promote to Provisional once the design has settled and a conformance harness is sketched |
| **Pre-interface** | Concept exists as documentation or aspiration; no interface code yet; behaviour lives inside specific providers and is not portable | A primitive has been identified but the contract has not yet been written | Promote to Experimental when a second consumer forces the design |

The progression is **Pre-interface → Experimental → Provisional → Stable**.
Demotions happen (and are noted) when a discovered leak forces a redesign.

## Semantic conformance

Signature conformance — does the provider expose the right methods with
the right argument and return types — is necessary but not sufficient.
The harder bar is **semantic conformance**: does the provider behave
the way consumers expect under the cases the interface specifies?

The repo distinguishes:

- **Required semantics** — every provider claiming the interface must
  honour these. Conformance test failure is a binding-eligibility
  failure; the provider is not eligible for the primitive slot in any
  persona.
- **Capability semantics** — opt-in behaviours providers may advertise
  via `supports(capability_name) -> bool`. Roles declare requirements;
  the binding validator (see `primitives-and-providers.md` →
  "Role portability") rejects persona configurations where a required
  capability is not supplied.
- **Provider-specific semantics** — behaviour that intentionally diverges
  and is documented per provider. A role that depends on this must opt
  in explicitly and is no longer persona-portable.

Each entry below names known semantic conformance points alongside its
known leaks. Required semantics that are not yet specified are also
called out — they are gaps in the contract.

## Conformance against managed providers

A practical constraint that affects every entry: conformance suites
cannot run end-to-end against managed providers in CI without cloud
credentials, network access, and spend. The repo's practice is a
two-tier conformance regime:

- **Local conformance** — runs against real providers in CI on every
  PR. Local providers (Ollama, LangGraph checkpointers, OpenBao,
  self-hosted Langfuse, local Postgres + Graphiti) are the conformance
  baseline.
- **Managed conformance** — runs in two modes: against mocks of the
  managed provider in CI on every PR, and against the real managed
  provider in a periodic verification job (cadence per provider,
  documented in the entry). Mock drift is a documented risk; periodic
  verification is the mitigation.

A provider's stability classification depends on which tier it can
satisfy. A managed provider cannot reach **Stable** without an active,
green periodic verification job. A managed provider's mock conformance
can support **Provisional** but does not on its own justify higher.

Conformance is always **per-deployment** (per bound persona), not
multi-tenant. A provider proves it satisfies the interface for one
persona at a time. This is a direct consequence of git-as-multi-tenancy
(see `primitives-and-providers.md` → "What's actually novel"):
multi-tenant scenarios are not part of the contract, because two
personas never share a process. Cross-deployment behaviour
(e.g. one persona delegating to another) is an A2A protocol concern,
not a provider conformance concern.

## Cross-primitive constraints

Some role requirements span multiple primitives. The binding validator
must express constraints that involve more than one interface:

- `interrupt_resume` requires harness support **and** session-store
  checkpoint support **and** memory replay safety.
- `tool_streaming` requires harness streaming support **and** capability
  registry projection streaming **and** observability span propagation
  across stream boundaries.
- `cross_persona_audit` requires identity provider audit trail **and**
  observability span retention **and** memory `forget` support
  consistent with audit constraints.

These are not new primitives — they are **compatibility groups** that
the binding validator enforces. Each compatibility group has a name,
an enumeration of (primitive, capability) requirements, and the role
declarations that consume it. The enumeration lives in this document
under the relevant entries.

## Per-interface entries

Each entry below follows the same template:

- **Interface name** and code location (file:line if it exists)
- **Stability** — current level
- **Providers** — what implements it today
- **Conformance suite** — path to the shared test file, or "not yet"
- **Known leaks** — implementation assumptions that have crept into the
  contract
- **Open questions** — design decisions still pending

---

### `HarnessAdapter` and tier subclasses

- **Code:** `src/assistant/harnesses/base.py:20` (`HarnessAdapter`),
  `:32` (`SdkHarnessAdapter`), `:157` (`HostHarnessAdapter`)
- **Stability:** **Experimental** (downgrade candidate from earlier
  implicit "Provisional" — design will change as `AgentRegistry` and
  `CapabilityRegistry` land)
- **Semantic conformance points (currently unspecified — gaps):**
  - What does `invoke()` returning `str` *mean* when the model produced
    multi-block content (text + citations + tool traces)? Not specified
    for the sync path — but `astream_invoke()` (below) now gives the
    structured alternative for consumers that need it.
  - What guarantees does `spawn_sub_agent()` give about isolation (does
    the child share memory state? identity tokens? span context)? Not
    specified.
  - When does `create_agent` finish — after the LLM is reachable, after
    the first system prompt is loaded, after tools are bound? Not
    specified. Each adapter currently chooses.
- **Realized capability semantics:**
  - **`streaming`** — `astream_invoke(agent, message) ->
    AsyncIterator[HarnessEvent]` (`base.py:72`, P14a
    `harness-ag-ui-bridge`). Contract: begins with `RunStarted`, yields
    `TextDelta` / `ToolCall*` events, ends with `RunFinished`
    (two-phase error contract). No longer an open question — it is
    implemented and consumed by the AG-UI SSE transport.
  - **`delegation context`** — `spawn_sub_agent` takes an additive
    `context: DelegationContext | None = None` (`base.py:101`, P12
    `delegation-context`); `None` preserves pre-P12 behaviour exactly.
- **Capability semantics still needed (not yet declared):**
  `interrupt_resume`, `multi_agent_native`, `plan_mode`,
  `parallel_tool_calls`, `structured_output`.
- **Providers:**
  - `DeepAgentsHarness` (LangGraph) — `src/assistant/harnesses/sdk/deep_agents.py`
  - `MSAgentFrameworkHarness` (**real**, P5 `ms-graph-extension`
    archived) — `src/assistant/harnesses/sdk/ms_agent_fw.py`
  - `ClaudeCodeHarness` (Host tier, P1.8 `capability-protocols`) —
    exports config rather than executing
  - Pi harness — proposed, not yet implemented
- **Conformance suite:** **exists** —
  `tests/conformance/test_harness_adapter.py` covers `name()`,
  `harness_type()`, `create_agent()`, `invoke()`, and `spawn_sub_agent()`
  (including the P12 `context` parameter) against fixture persona/role.
  Cross-provider (DeepAgents vs MSAF) semantic conformance is still
  per-harness; a shared behavioural suite is the next step toward
  Provisional.
- **Known leaks:**
  - `invoke()` / `spawn_sub_agent()` return a `str`, assuming a single
    text reply. Sub-agent results may legitimately be structured
    (citations, tool traces, plan deltas). `astream_invoke` addresses
    this for the streaming path; the sync path still flattens. Move to a
    typed result envelope once a second harness exercises the structured
    path.
  - `create_agent()`'s `tools` and `extensions` arguments are
    `list[Any]` — the protocol doesn't constrain shape. Note that tools
    are now the harness-neutral `ToolSpec` (P17) rendered per-harness by
    `harnesses/tool_adapters.py`; the annotation should tighten to
    `list[ToolSpec]` when `CapabilityRegistry` becomes the discovery
    source.
  - `spawn_sub_agent()` lives on the harness at all — should move to
    `AgentRegistry` once that primitive exists. The current
    implementation constructs a same-type child, blocking cross-harness
    delegation (see `AgentRegistry` entry).
- **Open questions:**
  - Cancellation / interrupt: no method today; LangGraph and Pi both
    support it natively. The P24 approval interrupt/resume contract and
    P30 durable sessions provide the checkpoint substrate; a harness-level
    cancel/interrupt surface is still unshaped.
  - Memory wiring: DeepAgents wires session memory via the P30
    checkpointer (`harnesses/sdk/checkpointer.py`), MSAF via minimal
    prepend (D27). The interface still does not declare a `memory`
    constructor parameter; wiring remains per-adapter.

---

### `Extension` protocol

- **Code:** `src/assistant/extensions/base.py:66` (`tool_specs`), `:68`
  (`health_check`)
- **Stability:** **Provisional** (the flagship leak below is now
  resolved; holding at Provisional pending a conformance suite and a
  second real provider family — Google — landing)
- **Protocol shape (P17 `mcp-server-exposure`):** `name` +
  `tool_specs() -> list[ToolSpec]` + `health_check() -> HealthStatus`.
  Since P10 `extension-lifecycle`, extensions may also implement optional
  async hooks `initialize()` / `shutdown()` / `refresh_credentials()` —
  NOT required Protocol members, so private structural extensions stay
  compatible; subclass `ExtensionBase` for no-op defaults.
- **Providers:**
  - Real MS extensions (`ms_graph`, `outlook`, `teams`, `sharepoint`) —
    shipped, P5 `ms-graph-extension` archived (code only; disabled on
    `personal` until the work persona lands, P15)
  - Empty-tool stubs for `gmail`, `gcal`, `gdrive` — real Google
    extensions arrive in the `google-extensions` phase
- **Conformance suite:** not yet — extension health checks are
  per-extension. A `tests/conformance/test_extension.py` covering
  `name`, `tool_specs()`, and `health_check()` is owed.
- **Resolved leak (was the repo's flagship example):**
  - The **dual-surface methods** `as_langchain_tools()` and
    `as_ms_agent_tools()` that baked consumer identity into the protocol
    were **REMOVED** in P17 (tool-spec exit criterion, no shim retained).
    Extensions now emit the harness-neutral, MCP-shaped `ToolSpec`
    (`core/toolspec.py`); harnesses render it through per-harness
    adapters in `harnesses/tool_adapters.py` (LangChain `StructuredTool`,
    MSAF `FunctionTool`, `mcp.types.Tool`) and never derive tools from
    extensions directly. Adding a Pi consumer is now a new adapter, not a
    new protocol method.
- **Open questions:**
  - Should extensions declare their persona-affinity (e.g. "this
    extension is only for `work`") at the protocol level, or via
    persona-side config? Currently the latter (activation config lives in
    private persona repos), keeping the protocol persona-agnostic.
  - The relationship between `ToolSpec` (per-extension emission) and the
    unified `CapabilityRegistry` (proposed) — the registry would become
    the aggregation/projection layer over what extensions already emit.

---

### `CapabilityRegistry` (proposed)

- **Code:** not yet as a unified primitive; substantial precursor
  exists as `HttpToolRegistry` from archived P3 http-tools-layer
  (HTTP + OpenAPI discovery, `$ref` resolution, auth handling,
  registry pattern, `--list-tools` CLI flag). `ToolPolicy` protocol
  exists from P1.8 capability-protocols.
- **Stability:** **Experimental** (precursor real and shipping;
  lifting to a unified primitive with multiple projections is the
  proposed `capability-registry` phase)
- **Providers:**
  - `HttpToolRegistry` — partial implementation, current; four open
    follow-ups (#16–#19 in archived `http-tools-layer`)
  - Extensions exposed via `tool_specs() -> list[ToolSpec]` (P17); the
    per-harness rendering that used to be the dual-surface pattern now
    lives in `harnesses/tool_adapters.py`. A unified registry would
    aggregate these `ToolSpec`s rather than call extensions per consumer.
  - Self-hosted MCP gateway — planned projection target (P17 already
    exposes the MCP surface at `/mcp`)
  - CLI projection (`assistant tool …`) — partial today via
    `--list-tools`
  - AgentCore Gateway — slot-compatible if the canonical form is
    OpenAPI-compatible
- **Conformance suite:** not yet — design first.
- **Known leaks (design-time):**
  - OpenAPI 3.x as the canonical form is the right baseline but needs
    extensions: streaming/progress (`x-aa-streaming`), persona/role
    scoping (`x-aa-roles`), per-projection auth policy
    (`x-aa-auth.<projection>`). Define these as a vendor extension
    namespace before any extension publishes specs.
  - "Tool" vs "skill" vs "agent" — all three are capabilities at the
    registry level but they are not the same thing. The registry needs
    a `kind` field and the discovery API needs to filter by it.
- **Open questions:**
  - In-process vs out-of-process: is the registry a Python object the
    harness imports, or a service the harness queries over HTTP/MCP?
    Both, with the same canonical form — in-process for fast path,
    out-of-process for cross-runtime.
  - Authority for `GuardrailProvider.authorize(persona, role, capability,
    projection)`: does the registry call out to a separate provider, or
    is authorization baked into discovery results? Lean toward the
    former for clean separation.
  - Hot-add semantics: when an extension publishes a new capability,
    when is it visible to existing sessions? Next turn, or next session?
    Per-projection answer (MCP supports notifications; HTTP can poll).

---

### `MemoryManager`

- **Code:** `src/assistant/core/memory.py:20` (real, archived P2
  memory-architecture); `MemoryPolicy` protocol in
  `src/assistant/core/capabilities/` (real, archived P1.8
  capability-protocols)
- **Stability:** **Experimental** (real implementation exists; interface
  shape has known load-bearing leaks; conformance suite not yet
  written)
- **Providers:**
  - Postgres + Graphiti via `MemoryManager` (current);
    `PostgresGraphitiMemoryPolicy` auto-selected when `database_url`
    configured
  - Letta self-host, Zep self-host, mem0 self-host — candidates
  - LangGraph `PostgresStore` — could back the local provider directly
  - AgentCore Memory — managed slot once work persona lands (P15)
  - Foundry Memory — managed alternative for Azure-bound work persona
- **Conformance suite:** not yet — `MemoryPolicy` has tests but no
  cross-provider conformance harness exists. Required before lifting
  to Provisional.
- **Persona parameter — partially resolved (was a load-bearing leak):**
  - `get_context`, `store_fact`, `store_interaction`, `store_episode`,
    `search`, and `export_memory` now take `persona: str | None`
    (`memory.py:32` `_resolve_persona`). A manager can be **bound at
    construction** via `persona_name` (as `PostgresGraphitiMemoryPolicy`
    does), after which callers pass `None` and the instance resolves its
    own persona. This directly addresses the git-as-multi-tenancy
    critique: the instance already knows its persona, so the caller need
    not supply it.
  - **The binding is now enforced, not just convenient.**
    `_resolve_persona` **raises** if an explicit persona is passed that
    differs from the bound one — a bound manager refuses to operate on
    another persona rather than silently honouring either side. Unbound
    managers (the CLI/host construction sites) still require an explicit
    persona, so there is no regression there.
  - Remaining work: the parameter has not been *dropped* — it is
    optional. Fully removing it (making the instance the sole source of
    truth) still folds into the `binding-manifest` phase; the current
    optional-and-validated shape is the safe intermediate.
  - The MSAF "minimal-prepend" pattern (D27) treats memory as a
    read-only context source. The full interface supports
    write-through and async ingestion; the minimal-prepend pattern is
    fine as a read implementation but must not constrain the
    interface shape.
- **Semantic conformance points (currently unspecified — gaps):**
  - What does `get_context()` guarantee about freshness? Are writes
    from the same turn visible to subsequent `get_context()` calls?
    Not specified.
  - What does `store_fact()` guarantee about durability — is the call
    durable on return, or only after `session.commit()`? Implementation
    commits, but not documented in the interface.
  - Cross-thread / cross-process visibility within the same persona
    (e.g. scheduler writes + REPL reads): not specified.
- **Open questions:**
  - Distinction between session memory (this conversation) and
    long-term memory (across conversations). AgentCore models them
    as one service; Letta separates them; LangGraph treats
    checkpointers and stores as distinct. Current code couples them
    via `MemoryManager`; the binding-manifest phase should consider
    splitting `SessionStore` out.
  - Write-through vs async ingestion: Graphiti entity extraction is
    too slow for the hot path. Architecture: write to a fast log
    (Postgres `memory` table) synchronously; async pipeline distills
    into the persona's graph. Currently both happen synchronously;
    needs async pipeline for scale.
  - Forgetting: GDPR-shaped delete requests. Required for `personal`;
    likely required for `work` under employer policy. Define
    `MemoryManager.forget(query)` with provider-specific semantics.

---

### `ModelProvider` / `ModelRef`

- **Code:** `src/assistant/core/capabilities/models.py` (`ModelRef`,
  registry, capability tags), `capabilities/model_bindings.py`
  (per-consumer bindings), `capabilities/health.py`. Realized in P19
  `model-provider-routing`; contracted as capability slot #6 in P24.
- **Stability:** **Provisional** (real, cross-consumer bindings exist;
  the seam is exercised by both SDK harnesses plus direct calls)
- **Providers:** persona-level `models:` registry — named entries with a
  provider string (`anthropic:`, `openai:`, `google_genai:`,
  `google_vertexai:`, `bedrock_converse:`, `ollama:`, OpenRouter via an
  OpenAI-compatible `base_url`), capability tags (`fast`, `cheap`,
  `long-context`, `coding`, `vision`, `local-only`, `private-data-ok`),
  and ordered fallback chains.
- **Shape:** `core/model_router.py` resolves capability requirements to a
  harness-neutral `ModelRef`; thin per-consumer bindings adapt it
  (LangChain `init_chat_model` for DeepAgents, `agent-framework` chat
  clients for MSAF, a raw OpenAI-compatible client for direct calls such
  as embeddings/summarization). Per-persona API-key resolution goes
  through the `CredentialProvider` seam; budget enforcement rides
  `GuardrailProvider` via `ActionRequest(action_type="model_call")`; cost
  attribution flows through the existing telemetry spans.
- **Conformance suite:** binding-level tests exist; a cross-provider
  `tests/conformance/test_model_provider.py` (resolve → ModelRef →
  per-binding adaptation) would firm up the Provisional claim.
- **Known leaks:** the catalog format mirrors the OpenRouter `/models`
  schema so cloud entries sync verbatim and local entries are
  hand-authored in the same shape — a deliberate coupling to that schema,
  noted so a future OpenRouter format change is understood as a breaking
  input.
- **Open questions:** the catalog schema + pricing data are shared with
  `agentic-coding-tools`' cost-aware routing as **contracts, not code**
  (protocol-standards doc Part C); keeping the two in sync without a
  published package is an open operational question.

---

### `IdentityProvider` (proposed)

- **Code:** no unified agent-facing interface yet, but the
  **`CredentialProvider` seam** now exists (P24 contract 7): one lookup
  interface for secrets/API keys, with the existing `_env()` indirection
  as the default impl and an OpenBao backend landing in P25. The
  `bao-vault` skill covers OpenBao operations at the script level.
- **Stability:** **Pre-interface** for the broad identity concept;
  the credential-lookup slice is **Experimental** (seam defined, env
  impl shipping, OpenBao backend in progress)
- **Providers:**
  - OpenBao / HashiCorp Vault self-host — primary local provider
  - AgentCore Identity — managed, for `work` if employer is AWS
  - Azure Managed Identity — managed, for `work` if employer is Azure
  - AWS IAM / Workload Identity Federation — for non-AgentCore AWS
- **Conformance suite:** not yet.
- **Known leaks (design-time):**
  - Two concerns are conflated in the name "identity": (a) credentials
    the agent uses to call third-party APIs (OAuth tokens, API keys),
    (b) the agent's own workload identity for service-to-service auth.
    AgentCore Identity handles both; OpenBao primarily handles (a) via
    secret storage. The interface must distinguish these or providers
    won't slot.
  - Per-projection auth interacts with this: the `CapabilityRegistry`
    needs an `IdentityProvider` to resolve credentials when projecting
    a tool over HTTP that requires OAuth.
- **Open questions:**
  - Token refresh: managed providers handle it transparently; OpenBao
    requires explicit refresh logic. Should the interface paper over
    this, or expose it as a capability?
  - Audit trail: managed providers emit audit events; local Vault
    requires the caller to log. Surface as a capability.

---

### `SessionStore` / `SessionRegistry`

- **Code:** `src/assistant/harnesses/sessions.py:67` (`SessionRegistry`:
  create/lookup/resolve/expire by `thread_id`), `:56` (`Session`);
  `harnesses/sdk/checkpointer.py` (LangGraph checkpointer binding).
  Realized in P30 `durable-sessions`, contracted in P24
  `capability-protocols-v2` (seam #5).
- **Stability:** **Experimental** (real implementation exists for the
  DeepAgents harness; single-provider, no cross-provider conformance
  harness yet)
- **Providers:**
  - LangGraph checkpointer — `InMemorySaver` (default tier) and a
    **Postgres** durable tier (`sessions: {durable: true}` + database
    URL; migration 002 adds the durable schema)
  - `SqliteSaver`, `PostgresSaver` — slot-compatible
  - Pi `SessionManager` (JSON-L) — survives process restarts trivially
  - AgentCore session state, OpenAI Threads — managed
- **Conformance suite:** not yet as a cross-provider harness; the
  durable tier has direct tests. A `tests/conformance/test_session_store.py`
  covering create/lookup/resolve/expire is the next step toward
  Provisional.
- **Known leaks (design-time):**
  - LangGraph's `thread_id` is the session-identity concept the registry
    currently exposes directly. It should become an opaque `SessionId`
    type that providers map, rather than leaking the LangGraph name.
  - Forking and branching: Pi has it natively; LangGraph supports
    time-travel; managed providers vary. Surface as a capability, not
    a required method.
- **Open questions:**
  - The `SessionRegistry` lives under `harnesses/` today; whether it
    should be a top-level capability alongside `MemoryManager` (so the
    P7 scheduler and P6 A2A server can multiplex sessions without going
    through a harness) is unsettled.
  - Relationship to `MemoryManager`: session writes feed memory
    ingestion. The write hook so memory ingestion can subscribe to
    session writes without each harness re-implementing the bridge is
    still undefined.
  - Approval interrupt/resume (P24 seam #6) rides on this checkpoint
    substrate: a guardrail block checkpoints, suspends, and resumes on an
    approval decision. The suspend/resume contract is defined but its
    channel-agnostic surface (AG-UI now; email/messaging later) is still
    settling.

---

### `Sandbox` (proposed)

- **Code:** not yet — Pi has built-in `bash`; DeepAgents has no sandbox
- **Stability:** **Pre-interface**
- **Providers:**
  - Local Docker — primary local provider for code execution
  - Playwright self-host — for browser
  - e2b.dev self-host — alternative code sandbox
  - AgentCore Code Interpreter, AgentCore Browser — managed
  - OpenAI Code Interpreter — managed
- **Conformance suite:** not yet.
- **Known leaks:**
  - Code execution and browsing have legitimately different surfaces
    (file I/O semantics, network policy, output shapes). Splitting into
    `CodeSandbox` and `BrowserSandbox` is likely correct; deferred until
    a real cross-provider need exists.
- **Open questions:**
  - Resource limits as a capability: providers vary widely. Worth
    surfacing as part of the binding configuration so persona-side
    policy can constrain.

---

### `AgentRegistry` (proposed)

- **Code:** not yet — current spawn lives in `HarnessAdapter` as
  `spawn_sub_agent` (`harnesses/base.py:39`)
- **Stability:** **Pre-interface**
- **Providers:**
  - In-process Python registry — fast path for same-runtime spawning
  - A2A protocol — open standard for cross-process / cross-runtime
  - AgentCore Runtime invocations — managed cross-runtime path
- **Conformance suite:** not yet.
- **Known leaks (design-time):**
  - The current `spawn_sub_agent` constructs a same-type child harness
    (`DeepAgentsHarness(self.persona, role)` in `deep_agents.py:92`).
    This prevents cross-harness delegation (e.g., `personal` running
    DeepAgents delegating an MS-Graph subtask to MSAF). The registry
    must support cross-harness spawning explicitly.
- **Open questions:**
  - Routing policy: when a role asks to spawn, who decides which harness
    serves the child? Static (role declares preferred harness),
    dynamic (registry picks based on capability requirements), or
    hybrid? Hybrid is likely correct — role declares constraints,
    registry resolves.
  - Concurrency model: in-process spawns are tasks; A2A spawns are
    remote calls. The handle type returned must abstract over both.

---

### Observability (OpenTelemetry gen-ai)

- **Code:** `src/assistant/telemetry/` (Langfuse-backed); see also
  `docs/observability.md`
- **Stability:** **Provisional** (closest to Stable of any interface
  here — well-shaped, opt-in, real provider)
- **Providers:**
  - Langfuse self-hosted (current, default for `LANGFUSE_ENABLED=true`)
  - Noop provider (current, default)
  - Phoenix, Jaeger, Honeycomb — slot-compatible via OTel
  - AgentCore Observability, Datadog — slot-compatible via OTel
- **Conformance suite:** test coverage exists for the Langfuse provider
  (`tests/telemetry/`); cross-provider conformance is implicit via
  OTel itself. Adding a `tests/conformance/test_tracer.py` is a small
  next step.
- **Known leaks:** Graphiti queries are intentionally traced at the
  `MemoryManager` boundary, not at the Graphiti client layer, to avoid
  double-counting (`docs/observability.md`). This is correct, but it
  means the OTel attribute conventions for memory operations are
  repo-specific until the OTel gen-ai spec covers memory operations
  formally.
- **Open questions:**
  - Span attribute conventions for persona/role: not standardized.
    The repo uses `assistant.persona` and `assistant.role` (see
    `set_assistant_ctx` in `cli.py:223`). Either align with an emerging
    convention or document the choice as a repo-specific dialect.

---

### `SkillResolver` (deferred)

- **Code:** not yet — `.agents/skills/` consumed directly via filesystem
  walker; `agentic-coding-tools/skills/install.sh` is the upstream sync
- **Stability:** **Pre-interface**
- **Providers:**
  - Filesystem walker — current behaviour
  - Pi's skill discovery — natively reads the same directories; no
    adapter needed
- **Conformance suite:** not yet — interface not yet defined.
- **Why deferred:** the static-file approach works today. The
  interface lifts when (a) skills need to be loaded dynamically per
  turn based on a query, (b) skill matching needs to be policy-gated
  per role, or (c) a second discovery source materializes (e.g.,
  fetching skills from a registry).
- **Open questions:** none yet — design lives in the future.

## How entries change state

A change to any entry follows the same pattern:

1. A PR proposes the change (new entry, stability bump, leak added,
   conformance test landed).
2. The PR also touches `primitives-and-providers.md` if the row in
   that document needs updating (e.g., a new provider entered the
   matrix).
3. A leak being **discovered** does not by itself demote stability;
   a leak being **load-bearing** (consumers depending on it) does.
4. Stability promotions require the conformance suite. A primitive
   cannot graduate Experimental → Provisional without a conformance
   harness, even if a second provider exists.
5. Managed-provider claims of conformance require a periodic
   verification job (see "Conformance against managed providers"
   above). Mock-only conformance caps a provider at Provisional.

## Ledger drift mitigation

The ledger's value collapses to zero if entries lag the code. Two
mitigations, in increasing strength:

1. **Reviewer obligation (current):** any PR that modifies
   `src/assistant/harnesses/`, `src/assistant/extensions/`,
   `src/assistant/core/memory*` (when added),
   `src/assistant/telemetry/`, or related interface files must touch
   the corresponding ledger entry. Reviewers reject PRs that don't.
2. **CI gate (implemented):** `scripts/check-architecture-ledger-drift.py`
   fails when interface-bearing files change without touching
   `docs/architecture/interface-stability.md` or
   `docs/architecture/primitives-and-providers.md`. It diffs against the
   merge base with `origin/main` (so it sees the whole PR, not just the
   tip commit) and needs full history (`fetch-depth: 0`). A change that
   is genuinely not an interface change may bypass it by declaring
   `[skip-ledger: <reason>]` in a commit message — a reviewable
   declaration in history, printed in the CI log, rather than a token
   whitespace edit. See CLAUDE.md → "Architecture Ledger Drift Gate".

The ledger is meant to be edited frequently. A stale entry is worse
than a missing one — it silently lies to consumers about what they
can depend on. This baseline was reconciled on 2026-07-22 (see the
banner at the top); the discipline from here is to keep each entry
honest per PR rather than let a two-month gap reopen.

## Open meta-questions

Questions about the ledger itself rather than any specific entry:

- Should this document live in `docs/architecture/` or in
  `openspec/specs/`? OpenSpec handles requirement-shaped artifacts
  well, but interface stability is more of a continuously-maintained
  ledger than a delta. Current call: docs/architecture/, with OpenSpec
  changes referencing entries by name.
- Frequency of review: every PR that touches a primitive should
  consider whether the ledger entry needs updating. A quarterly
  consolidation pass keeps the ledger honest.
- Cross-link to the gotchas document: gotchas often surface from
  ledger entries (e.g., G6 is a privacy-boundary gotcha that connects
  to `MemoryManager` design). Reciprocal links from each gotcha to
  the relevant primitive are owed.
