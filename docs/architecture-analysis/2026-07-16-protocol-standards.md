# Protocol Standards & Ecosystem Decomposition — 2026-07-16

> Companion to `2026-07-16-ecosystem-pillars.md`. Two parts:
> (A) the **standards-first protocol matrix** — which existing standard each
> component seam adopts, and where our own protocols are deliberate
> placeholders; (B) **lessons from the functional decomposition of existing
> agent ecosystems** (AWS Bedrock AgentCore, LangChain/LangGraph, Codex,
> Claude Code, Pi, OpenClaw, Omnigent) and what they change in our design.
> Provenance reference for the P24 contract set.

## A. Protocol adoption matrix

Rule (roadmap guiding principle): **adopt an existing standard at every
seam where one has converged; where none has, keep our own protocol as a
placeholder — but shape it so migration to an emerging standard is a
mapping, not a rewrite.** Placeholders are marked ⧗.

| Seam | Standard to adopt | Status in repo | Notes |
|------|-------------------|----------------|-------|
| Service → tool description | **OpenAPI 3.x** | Adopted (P3 `http_tools` discovery) | Keep. OpenAPI is the *service* description; it compiles into the tool protocol below |
| Agent-facing tool protocol | **MCP** (tools/resources/prompts, JSON-RPC, streamable HTTP) | Planned (P17 server; P24 ToolSpec) | Internal `ToolSpec` = MCP tool schema shape (name, description, JSON-Schema input). OpenAPI-derived and extension tools compile into it; per-harness adapters render it native. Serving it over MCP (P17) becomes a transport, and MCP-speaking harnesses consume it directly |
| Agent ↔ agent | **A2A** (Linux Foundation; agent cards, tasks, `message:stream`) | Planned (P6) | Keep as planned. Agent card is also where P25 authn declarations live (A2A uses standard HTTP auth schemes) |
| Agent ↔ user UI | **AG-UI** (session/event channel) + **MCP-UI / MCP Apps** (tool-embedded UI) | AG-UI adopted (P14a); MCP-UI planned via P17/P29 | Two complementary layers: AG-UI is our session transport; MCP-UI/Apps is how tool results carry interactive UI when we're consumed *as* an MCP server. P29 multimodal parts follow AG-UI/MCP content-part types rather than inventing any |
| Model calling (wire) | **OpenAI-compatible** (Chat Completions — lingua franca of OpenRouter, vLLM, Ollama, NIM), **Anthropic Messages**, **Gemini generateContent**, Bedrock/Vertex | Partially (LangChain `init_chat_model` in DeepAgents only) | Do not invent a wire protocol. The in-process seam is the `ModelProvider` protocol resolving to a harness-neutral `ModelRef` (dialect, endpoint, credential ref, tags, pricing); **bindings** adapt it per consumer — LangChain `init_chat_model` (DeepAgents), `agent-framework` chat clients (MSAF), raw OpenAI-compatible client (direct calls: embeddings, summarization). `openai-compatible` alone covers OpenRouter + all local backends (GX10) |
| Model *metadata* (capability tags, pricing) | ⧗ none converged | P19 catalog | Placeholder: mirror the **OpenRouter `/models` schema** (id, pricing, context length, modalities) as the catalog format so cloud entries can be synced verbatim and local entries hand-authored in the same shape |
| Observability | **OpenTelemetry GenAI semantic conventions** | Langfuse provider (P4) | Harden: align span/attribute names to OTel GenAI semconv so the backend (Langfuse today, OpenLLMetry/other OTLP later) is swappable without touching call sites |
| Auth (service surfaces) | **OAuth 2.1 + MCP authorization spec**; A2A card auth schemes | Planned (P25) | Standard exists for the *transport* auth. ⧗ Agent *identity* (persona×role×delegation-chain principal) has no converged standard — SPIFFE-like workload identity is the closest analogue; keep `AgentIdentity` as placeholder shaped for it |
| Secrets & credential storage | **OpenBao** (Vault-compatible API; already operated as a service for the coding coordinator) | Planned (P25 backend; P24 contract 7 seam) | Reuse policy applied: share the stateful service. Per-persona policies/mounts, short-lived dynamic credentials, AppRole/JWT auth per agent principal, audit log. Fronted by a `CredentialProvider` seam whose default impl is the existing `_env()` indirection — a fresh clone (GX10) boots without a vault |
| Skills packaging | **Agent Skills** (`SKILL.md` folder format) | Partially (roles carry skills dirs; deepagents + Claude Code both consume) | Adopt the open format for role skills so the same skill folders serve DeepAgents, Claude Code, Codex, and Gemini CLI without translation |
| Memory | ⧗ none converged | Own `MemoryPolicy` (P2/P21) | Keep ours. Expose read paths as MCP resources (free interop); watch AgentCore Memory / Letta-style APIs as candidate shapes |
| Sandbox config | ⧗ none converged (OCI is the packaging substrate) | Own `SandboxConfig` (P24 planes) | Adopt **Codex's policy vocabulary** as the FS plane's named levels (`read-only` / `workspace-write` / `full-access`) + explicit network on/off — proven, human-legible; compiles to Docker/OpenShell/E2B backends |
| Evals | ⧗ none converged | gen-eval (adopted 2026-05-21) | Keep gen-eval scenario YAML as the placeholder format (P27) |
| Human seam (approvals, feedback, input) | **MCP elicitation** (when consumed as MCP server), **A2A `input-required` task state** (A2A surface), **AG-UI** events (own UI) | P24 contract 6 | One internal `ApprovalRequest`/decision shape mirroring MCP's elicitation schema; **channels are transports** that render it and capture the decision — AG-UI first, then email via existing extensions (Outlook code-complete, Gmail in P14; decision returns as reply or signed link), messaging later (P29 Channel binding). Checkpointed suspend makes hours-long email round-trips safe. Nothing new is invented except the internal shape and per-channel rendering |

## B. Lessons from ecosystem decompositions

### AWS Bedrock AgentCore — the strongest external validation

AgentCore decomposes an agent platform into à-la-carte services:
**Runtime** (sandboxed per-session), **Memory** (managed, with async
*strategies* — semantic extraction, summarization, user-preference
extraction — run post-session), **Gateway** (converts OpenAPI/Lambda/
services into MCP tools + tool search), **Identity** (agent identity +
OAuth token vault, distinguishing *inbound* auth from *outbound*
on-behalf-of flows), **Code Interpreter**, **Browser**, **Observability**
(OTel). This is nearly 1:1 with our capability slots — strong evidence
the slot architecture is right. Specific takeaways:

- **Gateway as a named component** ≈ our OpenAPI→ToolSpec compiler.
  Treat it as one module with one output type (P24 contract 2), not
  logic smeared across `http_tools` + per-harness wrapping.
- **Memory strategies** ≈ P28's consolidation jobs — validated shape:
  extraction runs *async after* the session, never inline in the loop.
- **Identity's inbound/outbound split** — P25 must model both: who may
  call *us* (A2A/MCP surface auth) and what *we* present when calling
  out on the user's behalf (token vault; today: ambient env vars).
- **Tool search** — when tool counts grow past a prompt-friendly number,
  retrieval-over-tools becomes a `ToolPolicy` concern. Design
  `authorized_tools` so a search/ranking stage can slot in (P24 note).

### LangChain / LangGraph

- **Durable execution = checkpointer, and it's pluggable.** Our
  DeepAgents harness already holds a LangGraph `InMemorySaver`
  (`deep_agents.py:92`); the durable-session contract (P24 contract 5)
  for this harness should simply be **adopt LangGraph's checkpointer
  interface with the Postgres implementation** rather than inventing a
  `SessionStore` — our own interface then only wraps thread listing +
  cross-harness parity.
- **Interrupts as first-class HITL.** LangGraph pauses a run, persists
  state, and resumes on human input. We have `ActionDecision.
  require_confirmation` (`capabilities/types.py:42`) that **nothing
  consumes** — no pause/resume machinery. P24 contract 6 (new):
  approval interrupt/resume — guardrail returns `require_confirmation`
  → harness suspends (checkpointer) → AG-UI surfaces the approval
  request as an event → resume with the decision recorded to the audit
  trail (P25 ties identity to the approval).
- **Agent Protocol** (runs/threads/store REST API) — candidate standard
  if we ever expose run management; note it in P6/P17 design, don't
  adopt yet.

### Codex (OpenAI)

- **Sandbox-first with named policy levels** (`read-only`,
  `workspace-write`, full access; network default-off) and **per-action
  escalation with justification** — adopt the vocabulary (matrix above)
  and the escalation flow: an action blocked by policy can carry a
  machine-readable escalation request into the P24 interrupt contract.
- **`AGENTS.md` convention** — already consumed by DeepAgents memory;
  keep it the harness-neutral repo-context file.
- Headless `exec` mode — mirrors our CLI/daemon split (P7); no change.

### Claude Code (host tier)

- **Hooks (pre/post tool use) as an extension seam** — our telemetry
  wrappers are an informal version. When P24 formalizes ToolSpec,
  define wrap points once (policy → telemetry → sandbox → execute) so
  hook-like extensions have a sanctioned place.
- **Permission modes** map cleanly onto guardrail presets — a persona
  could declare `guardrail_mode: plan|accept-edits|full` rather than
  bespoke config.

### Pi

- **Minimal-kernel discipline**: tiny core loop, everything else
  (tools, TUI, providers) as uniform extensions. Our core is already
  lean; the lesson is *restraint* — P24's six contracts are the kernel
  surface; resist adding slots beyond them.

### OpenClaw / Omnigent

- **Channel adapters separated from the agent core** (OpenClaw's
  Telegram/WhatsApp/email gateways): P29 should define a thin
  `Channel` = transport binding (AG-UI event stream ↔ external
  medium), not new agent code paths.
- **Runner-per-session with a session registry** (Omnigent server):
  our `web/app.py` builds **one harness at startup** — single global
  conversation. The P24 durable-session contract must include a
  session registry (create/lookup/expire by `thread_id`) or the P7
  daemon and P6 A2A server cannot multiplex users/tasks.

## C. Cross-repo reuse policy (assistant ↔ agentic-coding-tools ↔ agentic-content-analyzer)

Code generation has made *writing* code nearly free; it has not made
*divergence* free. Policy (candidate ADR under X3):

**Share contracts, data, and stateful services. Freely duplicate
stateless mechanism.**

- **Always share (drift here is a bug):**
  - *Stateful services* — `agentic-content-analyzer` owns its
    index/database and stays one service. It is consumed as tools:
    today via OpenAPI `http_tools` discovery (already wired — teacher
    role, P8 vault endpoints), via MCP whenever ACA grows an MCP
    surface. The P24 ToolSpec compiler makes OpenAPI-vs-MCP a
    non-decision — both compile to the same internal shape, so no
    migration pressure exists.
  - *Schemas & vocabularies* — the model-catalog format (OpenRouter
    `/models` mirror), capability-tag vocabulary, pricing data, eval
    finding schemas. One source (or duplicated files + a conformance
    test), consumed by both this repo's P19 router and
    `agentic-coding-tools`' cost-aware routing.
  - *Security-critical logic* — sanitization/redaction rules (P26
    reuses `telemetry/sanitize.py`; if ACT needs the same, share the
    ruleset as data, not a library).
- **Freely duplicate (regenerate targeted at the problem):** routers,
  retry wrappers, adapters, glue. ACT's cost-aware router solves
  vendor/tool routing for coding tasks; P19 solves per-persona
  chat/embedding model routing. Port the *design decisions*, write the
  code fresh. Two divergent implementations are fine when two divergent
  *answers* are fine.
- **Avoid cross-repo library imports** — the `gen-eval` path dependency
  (`[tool.uv.sources]`, finding H3) already demonstrates the cost:
  broken standalone clones. Libraries are the worst of both worlds here
  (coupling without a service boundary); prefer a service or a schema.

## D. Consequences folded into the roadmap

1. New roadmap guiding principle: **standards-first seams** (matrix
   above; placeholders must be migration-shaped).
2. P24 gains contract 6 — **approval interrupt/resume** (consume
   `require_confirmation`; checkpointer-suspend; AG-UI approval event;
   audited resume) — and two design notes: checkpointer adoption for
   sessions, session registry requirement.
3. P19 catalog format = OpenRouter `/models` schema mirror.
4. P4 follow-up inside P27: align telemetry attributes to OTel GenAI
   semantic conventions.
5. P25 models inbound vs outbound auth explicitly (AgentCore lesson).
6. Sandbox FS plane adopts Codex's named policy levels.
7. P24 contract 6 is **channel-agnostic**: `ApprovalRequest` mirrors MCP
   elicitation; AG-UI renders it first; email (Outlook/Gmail
   extensions) and messaging channels follow; A2A `input-required` and
   MCP elicitation represent it on the served surfaces.
8. Cross-repo reuse policy (Part C) becomes an ADR under X3; P19 shares
   the catalog schema + pricing data with `agentic-coding-tools`'
   cost-aware routing but not its code; ACA remains a service consumed
   as tools (OpenAPI today, MCP when available — same ToolSpec either
   way).
9. The model seam is generalized from "LangChain `init_chat_model`" to
   the `ModelProvider` → `ModelRef` → per-consumer-binding shape
   (init_chat_model is the LangChain binding, not the seam) — MSAF
   cannot consume LangChain model objects, and direct calls
   (embeddings, summarization) need no harness at all.
10. P24 gains contract 7: the `CredentialProvider` seam (env-var
    default impl), with OpenBao as the P25 production backend.
11. P28's loop is source-agnostic: `FeedbackEvent` →
    `ImprovementProposal` from human *and* machine sources, risk-tiered
    (`RiskLevel`) through the P24 approval gate — the human seam and
    the learning gate are one mechanism.
