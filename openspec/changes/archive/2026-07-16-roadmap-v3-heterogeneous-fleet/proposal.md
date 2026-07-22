# Proposal: roadmap-v3-heterogeneous-fleet

## Why

Roadmap v2 (2026-04-13) predates four material shifts in the project's
operating environment, documented in the 2026-07-07 architecture review
(`docs/architecture-analysis/2026-07-07-architecture-review.md`):

1. **Heterogeneous fleet is now the deployment reality** — ASUS Ascent
   GX10 (128 GB unified-memory GB10 node for local inference + always-on
   work) and PowerSpec G762 (workstation), alongside Claude/Gemini/Codex
   subscription seats, OpenRouter, and hyperscaler model gardens. v2
   assumed a single Anthropic API key and Railway as the deployment
   target, and listed multi-model routing as out of scope.
2. **Meta-harnesses emerged** — Databricks Omnigent (open-sourced
   2026-06, Apache 2.0: runner+server control plane composing Claude
   Code/Codex/Pi/LangGraph/custom agents) and NVIDIA NemoClaw (hardened
   OpenShell sandbox runtime for always-on agents, explicitly supported
   on the GX10). The project needs a stated posture: compose *under*
   them, don't rebuild them.
3. **Roadmap drift** — `harness-ag-ui-bridge` (a phase change: added the
   `ag-ui-emitter` + `web-server` specs) was archived 2026-05-21 with no
   roadmap row and a colliding "P14" commit label; the
   `fix-harness-conversation-memory` fix (2026-05-15) is also unlisted.
   This violates the `tooling-roadmap` spec's "every phase change has a
   row" invariant.
4. **Built-but-inert memory** — all four `MemoryPolicy` implementations
   return `[]` from `get_recent_snippets()`; the highest-value user-facing
   capability (memory continuity) is buried as a "P5b candidate" note in
   CLAUDE.md instead of being a scheduled phase.

## What Changes

- **Rewrite `openspec/roadmap.md` as v3** (v2 preserved in git history):
  - Retroactive rows: `P14a harness-ag-ui-bridge` (archived phase),
    `X2 fix-harness-conversation-memory` (archived non-phase).
  - New phases: `P19 model-provider-routing`,
    `P20 local-inference-node`, `P21 memory-retrieval-activation`,
    `P22 meta-harness-compat`, `P23 deployment-topology`; new non-phase
    `X3 repo-hygiene`.
  - Fold `railway-deployment` (v2 P18; never had a change directory)
    into P23 as an optional cloud variant.
  - Reframe `P11 harness-routing` (harness dimension only; model routing
    extracted to P19) and `P16 cli-harness-integrations` (register the
    missing `codex` host harness, add `gemini_cli`).
  - Updated dependency graph, recommended execution order, cross-cutting
    themes, and a v3 change log section.
- **Add `docs/architecture-analysis/2026-07-07-architecture-review.md`**
  as the canonical provenance reference for the new phases (analogous to
  `docs/perplexity-feedback.md` for v2 rows).
- **Modify the `tooling-roadmap` spec's Provenance Attribution
  requirement** to recognize architecture-review documents under
  `docs/architecture-analysis/` as a citable provenance source (the v3
  rows cite "arch-review G-x" findings).
- **2026-07-16 amendment (owner ecosystem brief)**: add
  `docs/architecture-analysis/2026-07-16-ecosystem-pillars.md` mapping
  the six ecosystem pillars (model routing; memory + continual learning;
  orchestration + agent IAM + clean-room sharing; sandboxing;
  eval/simulation feedback loop; multimodal I/O) to phases, and add
  roadmap rows **P24 `capability-protocols-v2`** (contracts-only
  pre-phase codifying the five seam gaps: ModelProvider capability slot,
  MCP-shaped ToolSpec, three-plane SandboxConfig, create_agent cleanup,
  durable sessions) and **P25–P29** (`agent-iam`,
  `knowledge-clean-room`, `eval-simulation-loop`, `continual-learning`,
  `multimodal-io`). Cross-persona bridge and role learning re-enter
  scope as P26/P28.
- **2026-07-16 amendment 2 (protocol standards)**: add
  `docs/architecture-analysis/2026-07-16-protocol-standards.md` — the
  standards-first adoption matrix (OpenAPI, MCP, A2A, AG-UI/MCP-UI,
  model wire APIs, OTel GenAI, Agent Skills, OAuth 2.1/MCP-auth;
  placeholders where no standard converged) and functional-decomposition
  lessons from AgentCore/LangGraph/Codex/Claude Code/Pi/OpenClaw.
  Roadmap gains guiding principle 7; P24 gains the approval
  interrupt/resume contract; P19/P25 descriptions sharpened.
- **2026-07-16 amendment 3 (human-seam channels + reuse policy)**: the
  approval contract is channel-agnostic (MCP-elicitation-shaped
  `ApprovalRequest`; AG-UI, then email/messaging via existing
  extensions; A2A `input-required` on served surfaces), and the
  protocol-standards doc gains Part C — the cross-repo reuse policy
  (share contracts/data/stateful services, duplicate stateless
  mechanism; ACA consumed as tools, P19 shares catalog schema with
  agentic-coding-tools' cost-aware routing).
- **2026-07-16 amendment 4 (model seam, OpenBao, feedback loop)**:
  model seam generalized to `ModelProvider` → harness-neutral
  `ModelRef` → per-consumer bindings (LangChain `init_chat_model`
  demoted to the LangChain binding — MSAF cannot consume LangChain
  models, and embeddings/summarization need no harness); P24 gains
  contract 7 (`CredentialProvider` seam, env-var default) with OpenBao
  (already operated for the coding coordinator) as P25's vault backend;
  P28's improvement loop made source-agnostic (`FeedbackEvent` →
  `ImprovementProposal` from human and machine sources, risk-tiered via
  `RiskLevel` through the P24 approval gate).

## What Does NOT Change

- No production code or tests are modified by this change.
- All v2 archived rows are preserved verbatim; no change-ids are renamed.
- Each new phase still gets its own `/plan-feature` → `/autopilot` cycle;
  this change does not pre-scaffold their proposal directories (same
  Approach-A rationale as v2).

## Impact

- Affected files: `openspec/roadmap.md` (rewrite),
  `docs/architecture-analysis/2026-07-07-architecture-review.md` (new),
  this change directory.
- Affected specs: `tooling-roadmap` (Provenance Attribution requirement
  MODIFIED — adds architecture-review as a provenance source). The
  change remains classified **non-phase** (meta proposal editing the
  roadmap itself; the spec edit only reconciles the roadmap's own
  invariants), and is therefore not listed in the roadmap table —
  matching the precedent of `roadmap-v2-reconciliation`.
- Risk: low (documentation-only). The main risk is planning churn if the
  fleet assumptions change; mitigated by keeping hardware specifics
  confined to P20/P23 scope text and the architecture review.
