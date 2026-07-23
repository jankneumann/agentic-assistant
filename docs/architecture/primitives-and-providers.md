# Primitives and Providers

This document is the architectural statement of `agentic-assistant`. It names
the agent-platform **primitives** the repo abstracts over, the **interfaces**
those primitives present, and the **providers** (local reference
implementations, third-party open-source projects, and managed services) that
can be plugged in behind each interface on a per-persona basis.

The single sentence: **the repo's value is not any one implementation; it is
the persona-scoped composition of selected providers behind stable interfaces,
with a privacy boundary between personas.**

## Architectural framing

This is the Service Provider Interface (SPI) pattern applied to agent
primitives. The same pattern shows up across software history:

- **JDBC / Python DB-API** — interface over relational databases; drivers per
  vendor; conformance test kits ensure swap-ability.
- **Kubernetes CRI/CNI/CSI** — interfaces over container runtime, networking,
  and storage; operators pick providers per cluster.
- **SQLAlchemy dialects** — one ORM surface, N database backends.
- **Terraform providers** — one config language, N cloud and SaaS targets.
- **OpenTelemetry exporters** — one instrumentation surface, N backends.

The pattern earns its keep when three disciplines are honoured: interfaces
stay narrow (every method is a coupling point), conformance tests verify
that any implementation satisfies the contract, and feature matrices
acknowledge legitimate per-provider divergence without polluting the core
interface.

A **persona** in this repo is a configuration bundle — which model, which
harness, which memory backend, which identity store, which tool catalog, which
observability backend — bound together with a private config repo (mounted as
a submodule under `personas/<name>/`) and its own database. A **role** is a
behavioural overlay (prompt, delegation rules, preferred tools) that runs
on top of whatever provider mix the persona selects.

### What's actually novel

Narrowed honestly: the load-bearing novelty in this repo is not the
persona-and-role concept itself (multi-tenant agent platforms achieve
analogous boundaries; role-as-system-prompt-fragment is well-explored).
The unprecedented combination is:

- **Git itself as the multi-tenancy mechanism.** Instead of building
  `tenant_id` into every table, API call, cache key, and policy check,
  the repo offloads multi-tenancy entirely to git access control,
  filesystem isolation, and per-persona process boundaries. The
  primitives are **single-tenant by design** because two personas
  never share a process; cross-persona work is cross-process (A2A).
  This mirrors how Unix achieves per-user isolation via the kernel
  rather than per-application code, how Kubernetes namespaces are
  enforced by the control plane rather than each operator, and how
  email isolates users via per-mailbox storage rather than a
  user-id column on a shared `messages` table. The choice collapses
  an enormous category of complexity that managed multi-tenant
  platforms (AgentCore, Foundry, OpenAI Assistants) have to carry.
- **Public code, private config via per-persona git submodules** is
  the mechanism that implements the architectural choice above. The
  public repo can ship open-source while every persona's credentials,
  role overrides, DB schema, and skill set live in independent private
  submodules under `personas/<name>/`. No managed agent platform
  offers this split because they assume cloud-hosted tenant isolation;
  no open-source framework offers it because they assume a single
  user.
- **A two-layer privacy guard** (`tests/_privacy_guard_plugin.py`
  plus `tests/conftest.py`) is the dev-time discipline that catches
  attempts to bake private content into public artifacts. It enforces
  the public/private split at test collection time (substring scan
  for private-persona identifiers) and at runtime (FS I/O patching
  against private paths). This is the artifact that turns the
  submodule split from convention into contract.

Persona-as-execution-boundary, role-as-overlay, and SPI-shaped provider
selection are the *delivery vehicle* for that novelty. They are not the
novelty themselves; they are well-trodden patterns adapted to carry
the git-as-multi-tenancy choice cleanly.

## The primitive table

Each row is a primitive. Each row defines an **interface** (the abstract
contract the repo owns), names current and prospective **providers** for it,
and notes whether the interface is currently realized in code, planned, or
still under design. Stability classification per interface lives in
[`interface-stability.md`](./interface-stability.md).

| Primitive | Interface (repo-owned contract) | Local / OSS providers | Managed providers |
|---|---|---|---|
| **Models** (LLMs) | `ModelProvider` / `ModelRef` (`core/capabilities/models.py`, realized P19) — capability-tagged registry → harness-neutral `ModelRef` → per-consumer bindings; budget via `GuardrailProvider`, keys via `CredentialProvider` | Ollama, vLLM, llama.cpp; OpenRouter (OpenAI-compatible `base_url`) as cross-provider façade | Anthropic, OpenAI, Google (`google_genai`/`google_vertexai`), Bedrock (`bedrock_converse`), Azure OpenAI, xAI, Groq, Fireworks, Together |
| **Harness / Framework** | `HarnessAdapter` (`src/assistant/harnesses/base.py:20`); SDK and Host tiers | DeepAgents/LangGraph (implemented), MSAF (**real**, P5), ClaudeCode (Host tier, P1.8), Pi (proposed), Strands, ADK, OpenAI Agents SDK, CrewAI, AutoGen | AgentCore Runtime, Bedrock Agents, OpenAI Assistants, Azure AI Foundry Agents, Vertex Agent Builder, Anthropic managed agents (when shipped) |
| **Capability Registry** | `CapabilityRegistry` (proposed) — publish, discover, project; OpenAPI canonical form with streaming and scoping extensions | `HttpToolRegistry` (current, partial); self-hosted MCP gateway projecting OpenAPI; CLI projection | AgentCore Gateway, OpenAI Tools, Azure Foundry Connectors |
| **Memory** | `MemoryManager` (`core/memory.py:21`, real) — read by query, ingest event, semantic search, per-persona isolation (bound at construction, mismatch-validated) | Postgres + Graphiti (implemented), Letta, Zep self-host, mem0 self-host, Cognee, LangGraph `PostgresStore` | AgentCore Memory, OpenAI Threads/Memory, Foundry Memory, Anthropic memory primitives (when shipped) |
| **Identity** | `IdentityProvider` (proposed) — credential vault for agent-to-tool/agent-to-service auth, workload identity | OpenBao / HashiCorp Vault (`bao-vault` skill); local OAuth flows | AgentCore Identity, Azure Managed Identity, AWS IAM, Workload Identity Federation, OpenAI service accounts |
| **Sessions / Checkpointing** | `SessionRegistry` (`harnesses/sessions.py:67`, real P30) — create/lookup/resolve/expire by `thread_id`; LangGraph checkpointer binding | LangGraph `InMemorySaver` (default tier) + **Postgres durable tier** (P30), `SqliteSaver`, `PostgresSaver`, Pi `SessionManager` (JSON-L) | AgentCore session state, OpenAI Threads, Foundry runs |
| **Observability** | OpenTelemetry gen-ai semantic conventions; thin `Tracer` wrapper at boundaries | Langfuse self-hosted (current, see [`observability.md`](../observability.md)), Phoenix, Jaeger | AgentCore Observability, Datadog, Honeycomb, LangSmith |
| **Sandboxes** (code, browser) | `Sandbox` (proposed) — bounded execution surface, capability-gated | Docker + Playwright, e2b.dev self-host, Pi built-in `bash` | AgentCore Code Interpreter, AgentCore Browser, OpenAI Code Interpreter, e2b.dev managed |
| **Agent Registry** | `AgentRegistry.spawn(...)` (proposed) — local in-process fast path; A2A for cross-process / cross-runtime | In-process Python registry; A2A bridge for cross-runtime | AgentCore Runtime invocations, OpenAI Assistants handoffs, Foundry agent orchestration |
| **Skill discovery** | `SkillResolver` (proposed) — given query, return matching skills; consume `~/.agents/skills/` and `.agents/skills/` layouts | In-repo skill walker (synced from `agentic-coding-tools/skills/`); Pi's native skill discovery | (No managed equivalent today) |

The repo holds the interface column. Providers in the local/OSS column are
either implemented, planned, or candidates the repo is positioned to adopt
without core changes. Providers in the managed column are slot-compatible
once interface adapters exist; they are not preconditions for the local
column to be useful.

## Example persona compositions

The provider selection is per-persona, not global. Two illustrative
compositions:

### `personal` persona — local-first, sovereign

| Primitive | Provider |
|---|---|
| Models | Claude via Anthropic API; Ollama for offline fallback |
| Harness | DeepAgents (LangGraph) for general reasoning; Pi for code/file/shell tasks (post-integration) |
| Capability Registry | Self-hosted MCP gateway over the repo's HTTP+OpenAPI tool registry |
| Memory | Local Postgres + Graphiti, scoped to `personas/personal/` DB |
| Identity | OpenBao vault holding personal API keys |
| Sessions | LangGraph `PostgresSaver` against persona-local Postgres |
| Observability | Self-hosted Langfuse (per `docs/observability.md`) |
| Sandboxes | Local Docker for code execution; Playwright for browser |
| Agent Registry | In-process Python registry |
| Skill discovery | Repo `.agents/skills/` synced from `agentic-coding-tools` |

### `work` persona — employer-cloud, leverage managed services

| Primitive | Provider |
|---|---|
| Models | Whichever frontier models the employer licenses (Claude / GPT / Gemini via Bedrock / Azure / Vertex) |
| Harness | MSAF for M365-shaped work; AgentCore Runtime for serverless agents |
| Capability Registry | AgentCore Gateway federating internal APIs and employer SaaS |
| Memory | AgentCore Memory (or Foundry Memory on Azure shops) |
| Identity | AgentCore Identity bridged to employer SSO / Azure Managed Identity |
| Sessions | AgentCore session state |
| Observability | AgentCore Observability → employer APM (Datadog / Splunk / etc.) |
| Sandboxes | AgentCore Code Interpreter, AgentCore Browser |
| Agent Registry | AgentCore Runtime + A2A for cross-process spawning |
| Skill discovery | Same as `personal` (skills are persona-portable) |

The role catalog (`roles/researcher`, `roles/triage`, `roles/coder`, etc.),
the persona × role prompt composition (`src/assistant/core/composition.py`),
the privacy guard (`tests/_privacy_guard_plugin.py`), the OpenSpec workflow,
and the skill discovery layer are **identical across both personas**. Only
the provider bindings differ.

## What's filled today vs. aspirational

Honest accounting of the matrix as of writing:

**Interfaces realized in code (real implementations shipping):**

- `HarnessAdapter` and its two tiers (`harnesses/base.py:12,24,48`) —
  narrow, but a planned shrink is expected once `AgentRegistry` and
  `CapabilityRegistry` land (sub-agent spawning and tool wiring move
  out of the adapter). DeepAgents harness implemented; MS Agent
  Framework harness implemented in P5 (archived).
- `Extension` protocol (`extensions/base.py:66`) — the leaky
  `as_langchain_tools()` / `as_ms_agent_tools()` dual-surface was
  **removed** in P17 `mcp-server-exposure`. Extensions now emit the
  harness-neutral `ToolSpec` (`core/toolspec.py`) via
  `tool_specs() -> list[ToolSpec]`, rendered per-harness by
  `harnesses/tool_adapters.py`. Real MS extensions ship (P5 archived);
  Google extensions pending (P14/google-extensions).
- `ToolSpec` (`core/toolspec.py`, P17) — the single internal,
  harness-neutral tool representation (MCP-shaped: name, description,
  JSON-Schema `input_schema`, async handler, `source` provenance).
  `ToolPolicy.authorized_tools()` is the sole aggregator; every tool
  source (extensions, OpenAPI-derived HTTP tools) compiles into it.
- `MemoryManager` (`core/memory.py:21`) — real, archived P2
  memory-architecture. Postgres + Graphiti dual-backed; auto-selects
  `PostgresGraphitiMemoryPolicy` when `database_url` configured.
  The former `persona: str` leak is now `persona: str | None`: the
  manager binds to a persona at construction and **raises on a
  mismatched explicit persona** (see "A known interface leak" below).
- `ModelProvider` / `ModelRef` (`core/capabilities/models.py`,
  `model_bindings.py`) — real, archived P19 model-provider-routing.
  Capability-tagged per-persona model registry resolving to a
  harness-neutral `ModelRef` with thin per-consumer bindings; both SDK
  harnesses and direct calls consume it instead of raw model-id strings.
- `SessionRegistry` + durable checkpointer
  (`harnesses/sessions.py`, `harnesses/sdk/checkpointer.py`) — real,
  archived P30 durable-sessions. LangGraph checkpointer with a Postgres
  durable tier (`sessions: {durable: true}`); session
  create/lookup/resolve/expire by `thread_id`.
- `HttpToolRegistry` + OpenAPI discovery from persona `tool_sources`
  — real, archived P3 http-tools-layer. Substantial precursor to the
  unified `CapabilityRegistry` proposed below. Four open follow-ups
  (#16–#19) address known gaps.
- Observability — real, archived P4 observability. Langfuse-backed
  with OTel-shaped spans on `HarnessAdapter.invoke()`,
  `DelegationSpawner.delegate()`, and memory operations.
- Capability protocols (`GuardrailProvider`, `SandboxProvider`,
  `MemoryPolicy`, `ToolPolicy`, `ContextProvider`) and
  `CapabilityResolver` — real, archived P1.8 capability-protocols.

**Interfaces planned but not yet defined as unified primitives:**

- `CapabilityRegistry` — unifying primitive over `HttpToolRegistry`
  plus extension tools and MCP servers, with multiple consumer
  projections (LangChain, MSAF, Pi, MCP, CLI). Design pending in
  the proposed `capability-registry` phase.
- `IdentityProvider` — OpenBao integration exists at the script
  level (`bao-vault` skill) but no agent-facing interface yet.
- `Sandbox` — currently per-harness. Lift when sandbox use becomes
  cross-harness.
- `AgentRegistry` — implicit in `spawn_sub_agent` today; should be
  lifted out of `HarnessAdapter`.
- `BindingManifest` — declarative deployment artifact unifying
  `persona.yaml` + harness config + capability bindings + sink
  configuration. Proposed as a foundational phase.

**Interfaces deferred:**

- `SkillResolver` — `.agents/skills/` layout is stable and
  consumed directly today; formal interface waits until dynamic
  skill loading per turn matters.

## Cross-cutting concerns the matrix hides

The primitive table draws clean per-row separations. Real systems have
wiring between rows, and these cross-cuts are where SPI patterns
classically leak. Naming the cross-cuts explicitly here so they are
not rediscovered per integration:

- **Event-schema agreement** between `HarnessAdapter` (emits) and
  `MemoryManager` (consumes). The two interfaces share a vocabulary —
  user message, assistant message, tool call, tool result, plan delta —
  that neither interface "owns." A normalized event envelope must live
  at the architecture level, not inside any one provider.
- **Span propagation** across `HarnessAdapter` → `CapabilityRegistry` →
  `IdentityProvider` → external API. OTel context propagation
  conventions must be shared and enforced; otherwise traces fracture
  at the first cross-primitive boundary.
- **Identity reference vocabulary.** When `CapabilityRegistry` projects
  an HTTP tool that requires OAuth, the projection layer must call
  `IdentityProvider` with a stable identifier for "which credential
  for this persona/role/projection." That identifier is shared
  vocabulary; both primitives must agree on its shape.
- **Session ↔ memory write hook.** `SessionStore` writes feed
  `MemoryManager` ingestion. Each harness must not re-implement the
  bridge; define the hook once.
- **Compatibility groups.** Some role requirements span multiple
  primitives (e.g. `interrupt_resume` needs harness support + session
  checkpoint support + memory replay safety). The capability matrix
  is per-interface; the binding validator must express constraints
  *across* interfaces or it cannot reject incompatible provider mixes
  at startup. Compatibility groups are formalized as artifacts within
  the proposed `binding-manifest` phase (the binding manifest is the
  declarative artifact the validator runs against); until that lands,
  they are documented here as a convention rather than enforced.

These cross-cuts are not new primitives. They are conventions that
several primitives must agree on. They live in this document and the
stability ledger; they do not get their own interface.

## Role portability — with caveats

The doc's strongest claim — that role definitions are persona-portable —
holds at the prompt and tool catalog layers but **not unconditionally
at the execution layer**. The same role YAML produces:

- **Identical prompts** on any binding (composition is provider-agnostic).
- **Identical tool catalogs** when the bound capability registry has the
  required capabilities (matrix check at startup).
- **Divergent execution semantics** for advanced features. A role with
  `delegation.allowed_sub_roles` spawns via graph nodes on LangGraph,
  via handoffs on MSAF, via extension-built routing on Pi. The *outcome*
  is similar in shape; the *guarantees* differ (graph spawn can run in
  parallel; handoff is sequential by default).

Portability discipline: roles declare their required capabilities
explicitly; the binding validator rejects persona configurations whose
provider mix cannot supply them; provider-specific behaviour is opt-in
via capability declarations, never silent.

## Binding-shaped vs migration-shaped primitives

Not every provider swap is a config change. Distinguishing:

- **Swap-shaped** (binding is config; the change is hot or near-hot):
  Models (no state), Observability (sinks accept arbitrary streams),
  Sandboxes (per-invocation, stateless from the architecture's view),
  Capability Registry (provider catalogs can be merged or swapped),
  Skill discovery (filesystem is filesystem).
- **Migration-shaped** (binding implies a deployment event; data or
  state must move): Memory (long-term storage of facts, entities,
  timelines), Sessions (resumable conversation state), Identity
  (tokens and credentials must be re-issued in the new vault).
- **Borderline** (mostly swap, with state in some implementations):
  Harness / Framework — runtime is stateless per-session, but bound
  sessions in flight don't survive a swap mid-session.

Treat migration-shaped primitives accordingly in operational planning:
they need a migration runbook per provider pair, not a config diff.

This pattern only delivers on its promise if three disciplines are followed:

1. **Conformance test suites per primitive.** Every interface has a test
   suite (`tests/conformance/test_<primitive>.py`) that any provider
   implementation must pass. JDBC has a TCK; Python's DB-API has a smaller
   one; this repo needs its own. Without conformance tests, the interface
   becomes documentation rather than a contract. The existing privacy guard
   (`tests/_privacy_guard_plugin.py`) is a precedent for cross-implementation
   conformance enforcement.

2. **Capability matrices, not feature parity.** Providers will diverge on
   advanced features (semantic search support, interrupt/resume, streaming
   shape, multi-modal input). Don't force the interface to the lowest
   common denominator. Each provider advertises capabilities
   (`MemoryManager.supports("semantic_search")`,
   `HarnessAdapter.supports("interrupt_resume")`); roles declare
   requirements; the persona's binding is rejected at startup if a required
   capability isn't supplied by its chosen providers.

3. **Narrow interfaces.** Each method on an SPI is a permanent coupling
   point. Before adding a method, ask whether it could be a capability on
   an existing method, a method on a different primitive, or pushed into a
   provider as a non-portable extension. The `Extension` protocol's
   dual-surface methods are an example of what *not* to do: they encoded
   consumer identity into the protocol and now have to be unwound.

## Privacy boundary

The persona-as-sovereign-execution-boundary is enforced by **deployment
topology**, not by defensive code in the primitive interfaces. Each
persona is a separate deployment with its own DB, its own credentials,
its own process. Two personas never share an address space, a connection
string, or a credential vault. Cross-persona reads are not "prevented by
the interface" — they are *physically impossible* because the topology
forbids shared infrastructure. The interfaces are single-persona by
design because, by topology, they will only ever be constructed inside
a process bound to exactly one persona.

This shifts what each layer of the privacy guard does:

- **Topology layer (load-bearing):** each persona is its own
  deployment — per-persona DB, per-persona vault, per-persona
  process. Run two personas, get two processes (same machine,
  separate hosts, separate clouds — all equivalent from the
  architecture's perspective). The primitives observe one persona
  at construction and never have a reason to know about others.
- **Code layer:** persona-specific config lives in private git
  submodules under `personas/<name>/`; the public repo never
  imports from them, only from fixture copies under
  `tests/fixtures/personas/`. This is the dev-time discipline that
  prevents private content from being baked into public artifacts.
- **Test layer:** the two-layer privacy guard
  (`tests/conftest.py` + `tests/_privacy_guard_plugin.py`) catches
  dev-time leakage at test collection (substring scan for
  private-persona identifiers) and at runtime (FS I/O patching).
  Its job is **narrow** — catch developer mistakes that would bake
  private content into public artifacts. It is not preventing
  runtime cross-tenant access, because the topology has already made
  that impossible.

A managed provider that cannot honour the topology constraint for a
given persona must not be eligible for that persona's binding.
AgentCore Memory holding `personal` long-term memory violates
`personal`'s explicit data-sovereignty constraint; the same provider is
appropriate for `work` if employer policy permits.

### A known interface leak — now largely closed

`MemoryManager` at `src/assistant/core/memory.py:21` historically took
`persona: str` as a required parameter on methods like `get_context()`,
`store_fact()`, and similar. Under git-as-multi-tenancy that was
**leakage from a defunct multi-tenant assumption**: each instance is
constructed inside a process already bound to exactly one persona (the
`session_factory` is per-persona), so the parameter could not validly
differ from the instance's persona.

This has since been addressed rather than merely tracked. The parameter
is now `persona: str | None`, the manager **binds to its persona at
construction** (`persona_name`), and `_resolve_persona`
(`memory.py:32`) **raises `ValueError` if a caller passes an explicit
persona that disagrees with the bound one** — a bound manager refuses to
touch another persona's data instead of silently honouring either side.
Bound callers pass `None` and the instance supplies the persona it
already knows. Unbound managers (the CLI/host construction sites) still
require an explicit persona, so those call sites are unchanged.

Remaining work is cosmetic, not correctness: the parameter is optional
rather than gone. Fully dropping it folds into the `binding-manifest`
phase. Tracked in
[`interface-stability.md`](./interface-stability.md) →
`MemoryManager`.

## Non-goals

Calling out things this architecture deliberately does **not** try to do:

- **Lowest-common-denominator features across providers.** Roles should
  declare what they need; bindings that can't supply it are rejected, not
  silently downgraded.
- **One-binding-per-repo.** The whole point is per-persona variation;
  pressure to "just pick a stack" should be resisted unless the second
  persona genuinely never materializes.
- **Reimplementing managed services for parity.** The local providers exist
  for sovereignty, learning, dev-loop speed, and air-gap scenarios — not
  to match feature-for-feature with AgentCore Memory or Foundry. Where
  the managed thing is dramatically better, the persona that needs it
  should bind to it.
- **Hiding provider identity from roles.** Roles can opt to require a
  specific provider when behaviour is provider-specific (e.g. a role that
  uses AgentCore Browser's session features). The capability matrix surfaces
  this rather than hiding it.

## Cross-references

- [`interface-stability.md`](./interface-stability.md) — per-interface
  stability classification and conformance status.
- [`../gotchas.md`](../gotchas.md) — subtle traps, several of which
  (G2, G6, G7) bear on the privacy boundary.
- [`../observability.md`](../observability.md) — the only primitive
  currently with end-to-end provider docs; templates the shape future
  primitive docs should follow.
- [`../../openspec/roadmap.md`](../../openspec/roadmap.md) — phase
  sequence; P5/P11/P15/P16 are where most provider-binding work lands.
