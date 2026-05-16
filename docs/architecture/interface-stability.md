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
  self-hosted Langfuse) are the conformance baseline.
- **Managed conformance** — runs in two modes: against mocks of the
  managed provider in CI on every PR, and against the real managed
  provider in a periodic verification job (cadence per provider,
  documented in the entry). Mock drift is a documented risk; periodic
  verification is the mitigation.

A provider's stability classification depends on which tier it can
satisfy. A managed provider cannot reach **Stable** without an active,
green periodic verification job. A managed provider's mock conformance
can support **Provisional** but does not on its own justify higher.

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

- **Code:** `src/assistant/harnesses/base.py:12, 24, 48`
- **Stability:** **Experimental** (downgrade candidate from earlier
  implicit "Provisional" — design will change as `AgentRegistry` and
  `CapabilityRegistry` land)
- **Semantic conformance points (currently unspecified — gaps):**
  - What does `invoke()` returning `str` *mean* when the model produced
    multi-block content (text + citations + tool traces)? Not specified.
  - What guarantees does `spawn_sub_agent()` give about isolation (does
    the child share memory state? identity tokens? span context)? Not
    specified.
  - When does `create_agent` finish — after the LLM is reachable, after
    the first system prompt is loaded, after tools are bound? Not
    specified. Each adapter currently chooses.
- **Capability semantics needed (not yet declared):**
  `streaming`, `interrupt_resume`, `multi_agent_native`, `plan_mode`,
  `parallel_tool_calls`, `structured_output`.
- **Providers:**
  - `DeepAgentsHarness` (LangGraph) — `src/assistant/harnesses/sdk/deep_agents.py`
  - `MSAgentFrameworkHarness` (stub → real in P5) —
    `src/assistant/harnesses/sdk/ms_agent_fw.py`
  - Pi harness — proposed, not yet implemented
- **Conformance suite:** not yet — current tests are per-harness, not
  cross-harness. A `tests/conformance/test_harness_adapter.py` covering
  `name()`, `harness_type()`, `create_agent()`, `invoke()`, and
  `spawn_sub_agent()` against a mock persona/role/tool fixture is
  prerequisite to a second non-stub implementation.
- **Known leaks:**
  - `spawn_sub_agent()` returns a `str` (`base.py:39-45`), assuming a
    single text reply. Sub-agent results may legitimately be structured
    (citations, tool traces, plan deltas). Move to a typed result envelope
    once a second harness exercises this path.
  - `create_agent()`'s `tools` and `extensions` arguments are
    `list[Any]` (`base.py:31-33`) — the protocol doesn't constrain shape.
    This will tighten once `CapabilityRegistry` is the discovery source.
  - `spawn_sub_agent()` lives on the harness at all — should move to
    `AgentRegistry` once that primitive exists.
- **Open questions:**
  - Streaming surface: `invoke()` is sync-shaped (`str` return). Should it
    return `AsyncIterator[Event]` instead? Likely yes; deferred until a
    consumer needs streaming (the CLI doesn't yet).
  - Cancellation / interrupt: no method today; LangGraph and Pi both
    support it natively. Add when needed.
  - Memory wiring: today each adapter wires its own memory (DeepAgents
    via `InMemorySaver`, MSAF via prepend). After `MemoryManager` lands,
    adapters consume from it; the interface should declare a `memory`
    constructor parameter.

---

### `Extension` protocol

- **Code:** `src/assistant/extensions/base.py:15`
- **Stability:** **Provisional** (with a known deprecation path)
- **Providers:**
  - Empty-tool stubs for `ms_graph`, `teams`, `sharepoint`, `outlook`,
    `gmail`, `gcal`, `gdrive` (`src/assistant/extensions/`)
  - Real MS extensions arrive in `ms-graph-extension` phase (P5)
  - Real Google extensions arrive in `google-extensions` phase
- **Conformance suite:** not yet — extension health checks are
  per-extension. A `tests/conformance/test_extension.py` covering
  `name`, `health_check()`, and the future `register()` is owed.
- **Known leaks (load-bearing):**
  - **Dual-surface methods** `as_langchain_tools()` and
    `as_ms_agent_tools()` (`base.py:19-21`) bake consumer identity into
    the protocol. Adding a Pi consumer requires either a third method
    (`as_pi_tools()`) or a refactor. Refactor is the right move: replace
    with `register(registry: CapabilityRegistry, persona: PersonaConfig)`
    once `CapabilityRegistry` exists. This is the cleanest example in the
    repo of a leaked interface.
- **Open questions:**
  - What does `register()` accept exactly? OpenAPI specs? Pure JSON
    Schema + handler references that the registry wraps into OpenAPI?
    Both? Resolution comes with the `CapabilityRegistry` design.
  - Should extensions declare their persona-affinity (e.g. "this
    extension is only for `work`") at the protocol level, or via
    persona-side config? Lean toward the latter to keep the protocol
    persona-agnostic.

---

### `CapabilityRegistry` (proposed)

- **Code:** not yet — partial precursor in `HttpToolRegistry` (HTTP +
  OpenAPI discovery from persona `tool_sources`)
- **Stability:** **Pre-interface**
- **Providers:**
  - `HttpToolRegistry` — partial implementation, current; four open
    follow-ups (#16–#19 in archived `http-tools-layer`)
  - Self-hosted MCP gateway — planned projection target
  - CLI projection (`assistant tool …`) — planned
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

### `MemoryManager` (proposed)

- **Code:** not yet — `MemoryPolicy` exists in MSAF stub
  (`harnesses/sdk/ms_agent_fw.py` D27 minimal-prepend) but is a workaround
  pattern, not the eventual interface
- **Stability:** **Pre-interface**
- **Providers:**
  - Local Postgres + Graphiti — planned in `memory-architecture` phase
  - Letta self-host — candidate
  - Zep self-host — candidate
  - LangGraph `PostgresStore` — could back the local provider directly
  - AgentCore Memory — managed slot once the work persona lands (P15)
  - Foundry Memory — managed alternative for Azure-bound work persona
- **Conformance suite:** not yet — design first.
- **Known leaks (design-time):**
  - The MSAF "minimal-prepend" pattern (D27) treats memory as a
    read-only context source. The full interface must support
    write-through and async ingestion; the minimal-prepend pattern is
    fine as a read implementation but must not constrain the interface
    shape.
  - Per-persona DB isolation is a hard constraint (CLAUDE.md): the
    interface must make cross-persona reads physically impossible.
    Concretely: `MemoryManager.__init__(persona: PersonaConfig)` binds
    to that persona; there is no `manager.get(persona=other, ...)`
    method. The privacy guard
    (`tests/_privacy_guard_plugin.py`) enforces this at the test layer.
- **Open questions:**
  - Distinction between session memory (this conversation) and
    long-term memory (across conversations). AgentCore models them as
    one service; Letta separates them; LangGraph treats checkpointers
    and stores as distinct. Decision: separate primitives
    (`SessionStore` vs `MemoryManager`) because their access patterns
    differ enough to warrant distinct interfaces.
  - Write-through vs async ingestion: Graphiti entity extraction is too
    slow for the hot path. Architecture: write to a fast log (Postgres
    table, or the harness's session store) synchronously; async
    pipeline distills into the persona's graph. The interface should
    expose both `ingest(events, sync=True|False)` and let providers
    decide which is supported.
  - Forgetting: GDPR-shaped delete requests. Required for `personal`;
    likely required for `work` under employer policy. Define
    `MemoryManager.forget(query)` with provider-specific semantics.

---

### `IdentityProvider` (proposed)

- **Code:** not yet — `bao-vault` skill exists for OpenBao operations
  but no agent-facing interface
- **Stability:** **Pre-interface**
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

### `SessionStore` (proposed)

- **Code:** not yet — LangGraph `InMemorySaver` used directly in
  `harnesses/sdk/deep_agents.py:60`
- **Stability:** **Pre-interface**
- **Providers:**
  - LangGraph `InMemorySaver`, `SqliteSaver`, `PostgresSaver`
  - Pi `SessionManager` (JSON-L) — interesting because it survives
    process restarts trivially
  - AgentCore session state — managed
  - OpenAI Threads — managed
- **Conformance suite:** not yet.
- **Known leaks (design-time):**
  - LangGraph's `thread_id` is a session-identity concept that not all
    providers expose. The interface should use an opaque `SessionId`
    type and let providers map.
  - Forking and branching: Pi has it natively; LangGraph supports
    time-travel; managed providers vary. Surface as a capability, not
    a required method.
- **Open questions:**
  - Lift this primitive now (force the design with one provider) or
    wait until a second harness needs the same checkpoint behaviour?
    Lean toward lift-on-second-consumer to avoid premature abstraction.
  - Relationship to `MemoryManager`: session writes feed memory
    ingestion. Define the write hook so memory ingestion can subscribe
    to session writes without each harness re-implementing the bridge.

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
2. **CI gate (planned):** a check that fails the build when an
   interface-bearing file is modified without a corresponding
   ledger touch. Implementation deferred; the obligation in (1) is
   the working agreement until the gate lands.

The ledger is meant to be edited frequently. A stale entry is worse
than a missing one — it silently lies to consumers about what they
can depend on.

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
