# Tasks: roadmap-v3-heterogeneous-fleet

## 1. Analysis

- [x] 1.1 Deep architecture/code review of `src/assistant/` (composition,
      capability protocols, harness tiers, memory, extensions, telemetry,
      model wiring) — findings in
      `docs/architecture-analysis/2026-07-07-architecture-review.md`
- [x] 1.2 External landscape grounding: Omnigent (Databricks), NemoClaw
      (NVIDIA), OpenClaw/Hermes, ASUS Ascent GX10 — sources cited in the
      review §6
- [x] 1.3 Reconcile OpenSpec state vs roadmap (found unlisted
      `harness-ag-ui-bridge` + `fix-harness-conversation-memory`, "P14"
      label collision)

## 2. Roadmap rewrite

- [x] 2.1 Write `docs/architecture-analysis/2026-07-07-architecture-review.md`
- [x] 2.2 Rewrite `openspec/roadmap.md` as v3 (retroactive rows, P19–P23,
      X3, P18 fold, P11/P16 reframe, updated DAG + execution order +
      themes + change log)
- [x] 2.3 Verify `tooling-roadmap` spec invariants: archived rows
      retained, every phase change has a row, provenance cited, DAG
      acyclic, statuses valid

## 2a. Ecosystem-brief amendment (2026-07-16)

- [x] 2a.1 Seam/abstraction audit of capability protocols vs the owner's
      six ecosystem pillars (models, tools, harnesses, sandboxes,
      evals/feedback, multimodal) — findings in
      `docs/architecture-analysis/2026-07-16-ecosystem-pillars.md`
- [x] 2a.2 Add roadmap rows P24 (contracts pre-phase) and P25–P29;
      update DAG, recommended order, cross-cutting themes, change log,
      out-of-scope (P26/P28 re-enter scope)

## 2b. Protocol-standards amendment (2026-07-16)

- [x] 2b.1 Standards-first protocol matrix (adopt vs placeholder per
      seam) + ecosystem decomposition lessons (AgentCore, LangGraph,
      Codex, Claude Code, Pi, OpenClaw/Omnigent) — in
      `docs/architecture-analysis/2026-07-16-protocol-standards.md`
- [x] 2b.2 Roadmap: add guiding principle 7 (standards-first seams);
      P24 gains contract 6 (approval interrupt/resume — the unconsumed
      `require_confirmation` gap) + checkpointer/session-registry notes;
      P19 catalog mirrors OpenRouter `/models` schema; P25 models
      inbound vs outbound auth

## 2c. Human-seam channels + cross-repo reuse (2026-07-16)

- [x] 2c.1 Human seam made channel-agnostic: `ApprovalRequest` mirrors
      MCP elicitation; AG-UI → email (Outlook/Gmail extensions) →
      messaging transports; A2A `input-required` / MCP elicitation on
      served surfaces (protocol-standards matrix row + P24/P29 rows)
- [x] 2c.2 Cross-repo reuse policy (Part C of protocol-standards doc):
      share contracts/data/stateful services (ACA stays a service
      consumed as tools; P19 shares catalog schema + pricing with
      agentic-coding-tools), duplicate stateless mechanism; ADR
      candidate added to X3

## 2d. Model-seam generalization, OpenBao, feedback abstraction (2026-07-16)

- [x] 2d.1 Generalize the model seam: `ModelProvider` → harness-neutral
      `ModelRef` → per-consumer bindings (LangChain init_chat_model /
      MSAF chat clients / raw OpenAI-compatible); principle 5, P19, P24
      contract 1 updated
- [x] 2d.2 OpenBao as the P25 vault backend behind a new P24 contract 7
      `CredentialProvider` seam (env-var default impl; P13 note)
- [x] 2d.3 P28 loop made source-agnostic: `FeedbackEvent` →
      `ImprovementProposal` from human + machine sources, risk-tiered
      via `RiskLevel` through the P24 approval gate

## 3. Validation & handoff

- [x] 3.1 `openspec validate roadmap-v3-heterogeneous-fleet --strict`
- [x] 3.2 Owner review of the v3 sequencing (especially P19/P21 priority
      and the P22 adopt-not-build posture) — approved 2026-07-16
      ("Reviewed road map, it looks good"); archived via
      `openspec archive roadmap-v3-heterogeneous-fleet`
