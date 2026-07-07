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

## 3. Validation & handoff

- [x] 3.1 `openspec validate roadmap-v3-heterogeneous-fleet --strict`
- [ ] 3.2 Owner review of the v3 sequencing (especially P19/P21 priority
      and the P22 adopt-not-build posture), then archive this change via
      `/openspec-archive-change roadmap-v3-heterogeneous-fleet`
