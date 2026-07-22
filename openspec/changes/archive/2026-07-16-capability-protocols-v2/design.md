# capability-protocols-v2 — Design

## Context

Contracts-only change. Each section below records the decision shape
for one of the seven P24 contracts and cites its provenance. The
authoritative sources are:

- `openspec/roadmap.md` — P24 row (seven contracts verbatim), guiding
  principles 5 ("one model seam, not two") and 7 ("standards-first
  seams").
- `docs/architecture-analysis/2026-07-16-protocol-standards.md` —
  protocol adoption matrix (Part A), ecosystem decomposition lessons
  (Part B), reuse policy (Part C), roadmap consequences (Part D).
- `docs/decisions/0005-model-seam-modelref-bindings.md` (ADR-0005) —
  the model seam decision.
- `docs/decisions/0006-cross-repo-reuse-policy.md` (ADR-0006) — share
  contracts/data/stateful services, duplicate stateless mechanism.
- Current code being extended: `src/assistant/core/capabilities/`
  (`types.py`, `resolver.py`, `tools.py`, `guardrails.py`,
  `sandbox.py`, `memory.py`) and `src/assistant/harnesses/base.py`.

Non-goal: implementation detail. Requirements are written to be the
review baseline for P19/P13/P22 (and P6/P7/P25) work packages.

## C1: ModelProvider as CapabilitySet slot #6

**Decision.** One model seam: a `ModelProvider` protocol that resolves
capability requirements to an ordered, non-empty fallback chain of
harness-neutral `ModelRef` values. `ModelRef` carries: `name`, wire
`dialect` (one of `openai-compatible`, `anthropic`, `gemini`,
`bedrock`, `vertex`), `endpoint`, `credential_ref` (a
`CredentialProvider` lookup key — never a secret value), capability
`tags` (`fast`, `cheap`, `long-context`, `coding`, `vision`,
`local-only`, `private-data-ok`), and pricing/metadata fields
mirroring the OpenRouter `/models` schema (pricing, context length,
modalities). Consumers adapt a `ModelRef` through thin **bindings**,
never through a second provider-abstraction library: LangChain
`init_chat_model` (DeepAgents), `agent-framework` chat clients (MSAF),
a raw OpenAI-compatible client for direct calls including embeddings.
Every model dispatch is budget-gated via
`GuardrailProvider.check_action(ActionRequest(action_type="model_call"))`
and cost-attributed through the existing telemetry spans.

**Provenance.** ADR-0005 (entire shape); roadmap guiding principle 5;
protocol-standards matrix rows "Model calling (wire)" and "Model
metadata" (OpenRouter `/models` mirror is the ⧗ placeholder — no
metadata standard has converged); consequence D.9 (init_chat_model is
a binding, not the seam); ADR-0006 (catalog schema + pricing data are
shared with `agentic-coding-tools` as data, router code is not).

**Pre-P19 default.** The contract needs a default so the resolver
contract is total before P19 lands: a `StaticModelProvider` that wraps
the persona's existing per-harness `model` config string into a
single-entry `ModelRef` chain (dialect inferred from the provider
prefix). Host harnesses get a `HostProvidedModelProvider` (the host
seat owns model choice). P19 replaces the SDK default with the real
registry + router.

## C2: MCP-shaped ToolSpec

**Decision.** One internal tool representation: `ToolSpec` with
`name`, `description`, `input_schema` (JSON Schema object — the MCP
tool schema shape), and an async callable `handler`, plus provenance
metadata (`source`). Everything compiles *into* it — OpenAPI-derived
HTTP tools (the P3 `_build_tool()` pipeline) and extension tools — and
per-harness **adapters** render it native (LangChain `StructuredTool`
for DeepAgents, `agent-framework` tool shape for MSAF, MCP tool
listing for the P17 server). `Extension.as_langchain_tools()` /
`as_ms_agent_tools()` are deprecated in favor of a single
`tool_specs()` method; the per-harness methods survive only as a
compatibility shim until the consuming phases migrate the adapters.

**Provenance.** Protocol-standards matrix row "Agent-facing tool
protocol" (MCP; internal ToolSpec = MCP tool schema shape so serving
over MCP in P17 is a transport, not a translation); Part B AgentCore
lesson "Gateway as a named component ≈ our OpenAPI→ToolSpec compiler
— one module with one output type, not logic smeared across
`http_tools` + per-harness wrapping"; Part C (OpenAPI-vs-MCP becomes a
non-decision for ACA consumption); roadmap P24 contract 2.

## C3: SandboxConfig v2 — three planes + named enforcement seam

**Decision.** `SandboxConfig` grows three typed planes: **filesystem**
(named levels `read-only` | `workspace-write` | `full-access`, plus
explicit mounts), **network** (deny-by-default egress with an
allow-list and optional proxy), **credentials** (an explicit secret
visibility set of `CredentialProvider` refs — nothing ambient). The
enforcement seam is *named*: tool invocation and the extension
subprocess boundary are where a `SandboxProvider` applies the config.
`PassthroughSandbox` remains the default implementation — it accepts
v2 configs and enforces nothing, preserving current behavior until
P22 supplies a real provider (container/OpenShell-backed).

**Provenance.** Protocol-standards matrix row "Sandbox config" (⧗ no
standard converged; adopt Codex's policy vocabulary for the FS plane's
named levels — proven, human-legible, compiles to
Docker/OpenShell/E2B backends); Part B Codex lesson (sandbox-first,
network default-off); consequence D.6; roadmap P24 contract 3.

## C4: Approval interrupt/resume (channel-agnostic)

**Decision.** Consume `ActionDecision.require_confirmation`
(`capabilities/types.py:42`, currently consumed by nothing): when a
guardrail returns it, the run suspends via the durable-session
checkpoint (C5), a channel-agnostic `ApprovalRequest` is emitted whose
shape mirrors MCP elicitation (human-readable `message` +
`requested_schema` JSON Schema for the decision payload), risk-tiered
via the existing `RiskLevel`. Channels are transports that render the
request and capture the decision — AG-UI first, email and messaging
later; MCP elicitation / A2A `input-required` represent it on served
surfaces. Resume replays the recorded decision; every
request/decision pair lands in an audit trail. Codex-style
**escalation-with-justification** is supported: a denied action may
carry a machine-readable justification that re-enters the same
interrupt flow at elevated risk.

**Provenance.** Protocol-standards matrix row "Human seam" (MCP
elicitation mirror; channels-as-transports; checkpointed suspend makes
hours-long email round-trips safe); Part B LangGraph lesson
("interrupts as first-class HITL"; the `require_confirmation` gap) and
Codex lesson (escalation with justification); consequences D.2 and
D.7; roadmap P24 contract 6.

## C5: Durable sessions — checkpointer + session registry

**Decision.** Two halves. (a) SDK harnesses expose
checkpointer-backed session persistence; for DeepAgents this **adopts
the LangGraph checkpointer interface** (with the Postgres
implementation as the durable backend) rather than inventing a
`SessionStore` — the harness accepts an injected checkpointer,
`InMemorySaver` stays the in-process default. (b) A **session
registry** keyed by `thread_id` (create / lookup / expire) replaces
the one-global-harness-at-startup pattern in `web/app.py`, so the P7
daemon and P6 A2A server can multiplex users/tasks. The registry is
the lookup layer; the checkpointer is the persistence layer; the
existing `thread_id` transport-binding contract is unchanged.

**Provenance.** Part B LangGraph lesson ("durable execution =
checkpointer, and it's pluggable … adopt LangGraph's checkpointer
interface with the Postgres implementation") and Omnigent lesson
("runner-per-session with a session registry; `web/app.py` builds one
harness at startup"); consequence D.2 design notes; roadmap P24
contract 5.

## C6: create_agent(tools) cleanup — ToolPolicy is the sole aggregator

**Decision.** `ToolPolicy.authorized_tools()` is the *only* place
tools are aggregated, wrapped (telemetry), and filtered. Harness
`create_agent(tools, extensions)` implementations MUST NOT re-derive
tools from the `extensions` argument (today
`harnesses/sdk/deep_agents.py` re-wraps `as_langchain_tools()` output
that `DefaultToolPolicy` already aggregated — two sites that drift).
The `extensions` parameter remains for non-tool concerns (lifecycle,
health) but is no longer a tool source. Designing aggregation into
one seam is also what lets a tool-search/ranking stage slot into
`authorized_tools` later (AgentCore Gateway tool-search lesson)
without touching any harness.

**Provenance.** Roadmap P24 contract 4; Part B AgentCore lessons
(Gateway one-output-type; "tool search … design `authorized_tools` so
a search/ranking stage can slot in"); the existing
capability-resolver "Aggregated Extension Tools Are Traced"
requirement (which institutionalized the two aggregation sites this
contract collapses to one).

## C7: CredentialProvider seam

**Decision.** A single lookup protocol —
`get_credential(ref) -> str` — through which every secret/API-key
read flows: persona config env indirections (the scattered `_env()`
helpers in `core/persona.py` / `core/graphiti.py`), `ModelRef.
credential_ref` resolution in model bindings, HTTP tool-source auth
headers. Default implementation `EnvCredentialProvider` preserves
exact `_env()` semantics (empty/missing ref → `""`), so a fresh clone
boots with no vault. P25 swaps in the OpenBao backend behind the same
protocol without touching call sites. Inbound-vs-outbound credential
modeling (who may call us vs. what we present on the user's behalf) is
explicitly **P25 scope** — this contract is the outbound lookup seam
only.

**Provenance.** Protocol-standards matrix row "Secrets & credential
storage" (OpenBao; `CredentialProvider` seam with `_env()` default so
the GX10 clone boots vault-less); Part B AgentCore Identity lesson
(inbound/outbound split — deferred to P25, noted here); consequence
D.10; roadmap P24 contract 7; ADR-0006 (OpenBao is a shared stateful
service).

## Cross-cutting notes

- **Slot discipline (Pi lesson).** `CapabilitySet` grows exactly one
  slot (#6, `models`). `CredentialProvider` and the session registry
  are deliberately *not* slots — the first is a lookup seam injected
  where needed, the second is transport-layer infrastructure.
- **MODIFIED semantics.** Every MODIFIED requirement in the deltas
  restates the full existing requirement text and extends it —
  OpenSpec replaces the named requirement wholesale at archive time.
- **Naming.** New type names used across deltas: `ModelRef`,
  `ModelRequest`, `ModelProvider`, `StaticModelProvider`,
  `HostProvidedModelProvider`, `ToolSpec`, `FilesystemPlane`,
  `NetworkPlane`, `CredentialsPlane`, `ApprovalRequest`,
  `CredentialProvider`, `EnvCredentialProvider`, `SessionRegistry`.
  Implementations may adjust module placement, not shape or names,
  without a spec update.

## Owner review verdicts (2026-07-16)

All seven authoring judgment calls accepted. Amendments from review:
- C2 (ToolSpec): legacy `as_*_tools()` shim removal pinned as a P17
  `mcp-server-exposure` exit criterion (was: unscheduled).
- C8 (added post-review): `MemoryPolicy.get_recent_snippets` becomes
  async at the protocol level now, so P19+ consumers never build on
  the sync bridge; sync callers bridge only at true sync edges (host
  export). See specs/memory-policy delta; P21 implementation updated
  in the same session.
