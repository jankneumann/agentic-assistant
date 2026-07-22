# Architecture Review — 2026-07-07

> Deep design/architecture analysis of `agentic-assistant`, produced to seed
> the **roadmap v3** rewrite (`openspec/changes/roadmap-v3-heterogeneous-fleet/`).
> Scope: current-state assessment, gap analysis against the target operating
> model (multi-machine, multi-subscription, multi-provider), external
> landscape (meta-harnesses), and engineering/knowledge-management hygiene.

## 1. Target operating model (the "why" behind v3)

The assistant is intended to run across a **heterogeneous personal fleet**:

| Resource | Class | Role in the system |
|----------|-------|--------------------|
| ASUS Ascent GX10 | GB10 Grace Blackwell, 128 GB unified LPDDR5x, ~1 PFLOP FP4, DGX OS | Always-on inference + agent node: local models (NIM / vLLM / Ollama), embeddings, scheduler daemon, per-persona Postgres/FalkorDB |
| PowerSpec G762 | x86 desktop, discrete NVIDIA GPU | Interactive workstation: CLI/host-harness sessions, dev, secondary CUDA capacity |
| Claude / Gemini / Codex subscriptions | Flat-rate seats | Host-harness tier — interactive + coding work at zero marginal cost |
| OpenRouter + hyperscaler model gardens (Bedrock / Vertex) | Metered APIs | SDK-harness tier — breadth of models, burst capacity, work-persona compliance surface |
| Meta-harnesses (Omnigent, NemoClaw) | Control planes | Optional composition/governance layer *above* this repo's harnesses |

The v2 roadmap predates all of this: it assumes a single Anthropic API key,
Railway as the deployment target, and treats multi-model routing as
explicitly out of scope. v3 exists to close that gap.

## 2. Current architecture — what's actually there

~12,240 lines of source across 10 packages, ~22,900 lines of tests (1.9×
test:source). Spec-driven via OpenSpec; 14 archived changes, 25 capability
specs.

**Composition model.** Persona (execution boundary: DB, auth, tools —
private submodule) × Role (behavioral pattern — public) × Harness
(pluggable agent backend). Three-layer prompt composition in
`src/assistant/core/composition.py`. Sub-agents inherit persona, switch
role (`src/assistant/delegation/spawner.py`).

**Capability protocols** (`src/assistant/core/capabilities/`) — the
architectural centerpiece from P1.8: `GuardrailProvider`,
`SandboxProvider`, `MemoryPolicy`, `ToolPolicy`, `ContextProvider`,
assembled per (persona, harness-type, role) by `CapabilityResolver`
(`resolver.py:37`). Host harnesses get host-provided slots; SDK harnesses
get concrete implementations.

**Two-tier harness split** (`src/assistant/harnesses/base.py`):
- **SDK tier** (we own the loop): `deep_agents` (LangChain/LangGraph,
  real), `ms_agent_framework` (real, with a namespace-packaging caveat).
  Streaming via six discriminated `HarnessEvent` types; AG-UI SSE bridge
  (`web/`, `transports/ag_ui/`) shipped in `harness-ag-ui-bridge`.
- **Host tier** (external CLI owns the loop): `claude_code` (exports
  context/guardrails/tool manifests). The persona template also lists a
  `codex` host harness, but **no `codex` class is registered in
  `harnesses/factory.py`** — a latent config/code mismatch.

**Memory.** `MemoryManager` (Postgres + Graphiti/FalkorDB) is real and
exercised by `export-memory`, but **all four `MemoryPolicy`
implementations return `[]` from `get_recent_snippets()`** — no live
retrieval reaches any harness's context. DeepAgents uses LangGraph
`InMemorySaver` + file memory instead of `MemoryManager`. Memory is built
but not *felt* in daily use.

**Extensions.** Four MS-Graph extensions are code-complete (disabled until
the work persona lands); `gmail`/`gcal`/`gdrive` are stubs. Lifecycle
hooks (`initialize`/`shutdown`/`refresh_credentials`) not yet in the
protocol (P10 pending).

**Observability.** Langfuse-backed provider with graceful noop
degradation; `@traced_harness` captures per-invocation token usage via
LangChain callbacks. This is the natural substrate for **cost-aware
routing** — the plumbing to know what a model call cost already exists.

**Resilience.** Retry + circuit breakers (`core/resilience.py`) applied to
HTTP tools and extensions.

### Strengths worth preserving

1. **The persona/role/harness factoring is the durable asset.** Harnesses
   churn (the 2025–26 ecosystem proves it); private persona config +
   public roles + capability protocols are what survive harness swaps.
2. **The SDK/Host split anticipated the subscription-vs-API economics.**
   Host harnesses consume flat-rate seats; SDK harnesses consume metered
   tokens. No other change is needed to *represent* this — only routing
   policy to *exploit* it.
3. **Capability protocols mirror what meta-harnesses productize.**
   Omnigent's policies and NemoClaw's sandbox/network-policy engine are
   externalized versions of `GuardrailProvider`/`SandboxProvider`. The
   protocols make adopt-vs-build a swappable decision instead of a
   rewrite.
4. **Test and privacy discipline.** 1.9× test ratio, two-layer privacy
   guard keeping private persona data out of public tests.

## 3. Gap analysis vs the target operating model

**G-A. Single-provider model layer (highest impact).** Only
`langchain-anthropic` is wired; MSAF assumes OpenAI env keys. Model
choice is one string per harness per persona, keys come from ambient env
vars, and there is no routing, fallback, or budget logic. Grep confirms
zero `litellm`/`openrouter`/Google GenAI wiring.
*Direction:* keep LangChain `init_chat_model()` as the single seam
(DeepAgents already uses it; it natively covers `anthropic:`, `openai:`,
`google_genai:`, `google_vertexai:`, `bedrock_converse:`, `ollama:`, and
OpenRouter via an OpenAI-compatible `base_url`). Add a small
`ModelRouter` above it: persona-declared model registry with **capability
tags** (`fast`, `cheap`, `long-context`, `coding`, `local-only`,
`private-data-ok`) and ordered fallback chains, enforced by
`GuardrailProvider` budgets and priced via the existing telemetry.
Avoid adopting LiteLLM as a second abstraction unless `init_chat_model`
proves insufficient — one seam, not two.

**G-B. No local-inference tier.** Nothing targets the GX10. Local models
matter for three distinct reasons: (1) always-on scheduled work at zero
marginal cost, (2) privacy — memory summarization and embedding of
private persona data should never leave the LAN, (3) latency-insensitive
background delegation. The GX10 exposes standard OpenAI-compatible
endpoints via NIM/vLLM/Ollama, so once G-A lands, local models are just
another registry entry with `local-only`/`private-data-ok` tags.

**G-C. Subscription seats underused.** `codex` is referenced but not
registered; there is no `gemini_cli` host harness at all. The host tier
should cover all three seats, and the delegation layer should prefer the
host tier for interactive/coding work before spending API tokens.

**G-D. Meta-harness posture undefined.** Omnigent (Databricks, Apache
2.0, June 2026) composes Claude Code/Codex/Cursor/Pi/LangGraph agents
under a runner+server control plane with YAML-defined agents, policies,
session sharing, and pluggable sandboxes. NVIDIA NemoClaw hardens
always-on agents (OpenClaw/Hermes-class) inside OpenShell sandboxes with
routed inference (NIM) and network policy — and the GX10 is explicitly
marketed as supporting both OpenClaw and NemoClaw.
*Positioning:* this repo should stay the **persona/role/capability
layer** and treat meta-harnesses as optional control planes above it —
i.e., become *composable under* Omnigent (agent-YAML + common API
surface; the A2A server and MCP exposure phases are 80% of that surface)
and *deployable inside* NemoClaw/OpenShell on the GX10 (which also gives
`SandboxProvider` its first real implementation). Do **not** rebuild
session-sharing/control-plane features in-repo.

**G-E. Memory built but inert.** All `MemoryPolicy.get_recent_snippets()`
return `[]`; DeepAgents bypasses `MemoryManager`. For a personal
assistant, memory continuity is the single most user-visible capability.
Activating retrieval is cheap relative to what's already built and should
be pulled forward explicitly rather than living as a "P5b candidate"
buried in CLAUDE.md.

**G-F. Deployment story is stale.** P18 assumes Railway. The real
topology is: GX10 as always-on node (daemon + DBs + local inference),
G762 as workstation, cloud as optional burst. Needs service definitions
(systemd/compose), secrets handling, DB backup, and LAN exposure of the
AG-UI/A2A/MCP surfaces.

**G-G. Roadmap drift.** `harness-ag-ui-bridge` (a phase change — it added
the `ag-ui-emitter` and `web-server` specs) was archived 2026-05-21 with
commit label "P14", colliding with the roadmap's P14 `google-extensions`,
and has **no roadmap row** — violating the `tooling-roadmap` spec's
"every phase change has a row" invariant. `fix-harness-conversation-memory`
(2026-05-15) is likewise unlisted.

## 4. Engineering & knowledge-management hygiene

| # | Finding | Recommendation |
|---|---------|----------------|
| H1 | All 25 capability specs have `## Purpose: TBD` placeholders | Backfill one-paragraph Purposes; make "Purpose written" part of the archive checklist |
| H2 | `docs/decisions/` (ADRs) doesn't exist although repo skills reference it | Seed with retroactive ADRs for the load-bearing decisions: SDK/Host split, capability protocols, AG-UI adoption, privacy boundary, model-seam choice (this review's G-A) |
| H3 | `gen-eval` is a **path dependency** (`../agentic-coding-tools/...` in `[tool.uv.sources]`) | Breaks standalone clones on new machines (GX10!). Publish it, vendor it, or gate it behind an optional extra/dependency-group |
| H4 | `codex` harness in persona template but not in factory registry | Register or remove; add a test asserting template↔registry consistency |
| H5 | `agent-framework` v1.0.1 namespace-package quirk | Pin `agent-framework-core` directly (already documented in CLAUDE.md; execute it) |
| H6 | Guardrail/Sandbox providers are allow-all/passthrough stubs | Acceptable pre-P13, but budget enforcement (G-A) and NemoClaw sandboxing (G-D) both want real implementations — sequence them |
| H7 | `docs/architecture-analysis/` did not exist despite the refresh skill expecting it | This document seeds it; refresh via `/refresh-architecture` after major phases |

## 5. Recommendations → roadmap v3

New phases (details in `openspec/roadmap.md` v3):

- **P19 `model-provider-routing`** — model registry + capability-tagged
  router on the `init_chat_model` seam; OpenRouter/Bedrock/Vertex/Google
  entries; budget guardrails; cost attribution via existing telemetry.
- **P20 `local-inference-node`** — GX10 endpoints (NIM/vLLM/Ollama) as
  registry entries; local embeddings for Graphiti/memory; `local-only`
  routing tags for private-data operations.
- **P21 `memory-retrieval-activation`** — make `get_recent_snippets()`
  real; wire `MemoryManager` into DeepAgents context; promoted from the
  "P5b candidate" note in CLAUDE.md.
- **P22 `meta-harness-compat`** — Omnigent-composable agent definition +
  NemoClaw/OpenShell deployment evaluation; first real `SandboxProvider`.
- **P23 `deployment-topology`** — home-lab topology (GX10 + G762),
  service definitions, secrets, backups; absorbs `railway-deployment`
  (Railway demoted to an optional cloud variant).
- **X3 `repo-hygiene`** — H1–H5 above (non-phase change).

Reframed: **P11 `harness-routing`** now routes across *harnesses* using
P19's capability vocabulary (model routing lives in P19, not P11).
**P16 `cli-harness-integrations`** now explicitly includes registering
`codex` and adding `gemini_cli` host harnesses (subscription tier).

Recommended execution order: X3 → P19 ∥ P21 → P10 → P13 → P20 → P7 ∥
P6/P17 → P11 → P22 → P8/P12 → P14/P15/P16 → P23.

## 6. External references

- [Introducing Omnigent (Databricks blog)](https://www.databricks.com/blog/introducing-omnigent-meta-harness-combine-control-and-share-your-agents)
- [Omnigent GitHub (omnigent-ai/omnigent)](https://github.com/omnigent-ai/omnigent)
- [Omnigent on Databricks docs](https://docs.databricks.com/aws/en/omnigent/)
- [NVIDIA NemoClaw](https://github.com/NVIDIA/NemoClaw)
- [OpenClaw vs Hermes vs Nemoclaw comparison](https://www.remoteopenclaw.com/blog/open-source-ai-agents-2026-comparison)
- [OpenClaw vs Hermes: control plane vs learning loop (The New Stack)](https://thenewstack.io/openclaw-hermes-agent-harness/)
- [ASUS Ascent GX10 product page](https://www.asus.com/networking-iot-servers/desktop-ai-supercomputer/ultra-small-ai-supercomputers/asus-ascent-gx10/)
- [Running a local LLM stack on the GX10](https://sleepsort.be/blog/local-llm-stack-asus-ascent-gx10/)
