# Tasks — roadmap-v2-perplexity-integration

Planning-only change. All tasks are documentation edits; tests validate
roadmap invariants via `openspec validate --strict` rather than runtime
behavior.

## Phase 1 — Canonical reference

- [ ] 1.1 Write test: verify `docs/perplexity-feedback.md` exists and
  contains all twelve §8 item headings (§8.1 through §8.12)
  **Spec scenarios**: tooling-roadmap — "Phase sourced from perplexity
  feedback"
  **Contracts**: N/A
  **Design decisions**: D6
  **Dependencies**: None
- [ ] 1.2 Create `docs/perplexity-feedback.md` by copying the review
  verbatim (from the planning conversation) into the file. Preserve all
  § numbering exactly so `roadmap.md` citations resolve.
  **Dependencies**: 1.1

## Phase 2 — Roadmap rewrite

- [ ] 2.1 Write test: verify `openspec/roadmap.md` phase-sequence table
  lists all 18 phases (P1 archived, P1.5, P2–P18) with non-empty
  change-ids and status values.
  **Spec scenarios**: tooling-roadmap — "Every in-progress change has a
  roadmap row", "Archived changes remain listed with archived status"
  **Contracts**: N/A
  **Design decisions**: D2, D4, D5
  **Dependencies**: 1.2
- [ ] 2.2 Write test: verify the Dependency graph section's phase names
  are a subset of the phase-sequence-table's change-ids (no dangling
  references). Parse the graph as a DAG and assert acyclicity.
  **Spec scenarios**: tooling-roadmap — "Prerequisites reference real
  phases", "Graph is acyclic"
  **Design decisions**: D2
  **Dependencies**: 2.1
- [ ] 2.3 Rewrite `openspec/roadmap.md` per design.md:
  - Guiding principles section
  - 18-row phase sequence table (P1 archived, P1.5, P2–P18) with
    change-id, status, perplexity §, source, description columns
  - Status lifecycle section (pending → in-progress → archived)
  - Dependency graph section rendered as ASCII tree
  - Per-phase execution playbook (plan → autopilot → archive)
  - Cross-cutting themes table
  - Out-of-scope section carrying forward the Phase-16 deferrals
  **Dependencies**: 2.1, 2.2

## Phase 3 — Capability spec

- [ ] 3.1 Write test: `openspec validate roadmap-v2-perplexity-integration
  --strict` exits 0.
  **Spec scenarios**: all four ADDED requirements under tooling-roadmap
  **Design decisions**: D6
  **Dependencies**: None
- [ ] 3.2 Create
  `openspec/changes/roadmap-v2-perplexity-integration/specs/tooling-roadmap/spec.md`
  with ADDED Requirements:
  - "Roadmap Document Authoritative" + 2 scenarios
  - "Phase Status Lifecycle" + 2 scenarios
  - "Dependency Graph Representation" + 2 scenarios
  - "Provenance Attribution" + 2 scenarios
  All SHALL/MUST language placed near the start of each requirement
  body (gotcha G5 from docs/gotchas.md).
  **Dependencies**: 3.1

## Phase 4 — Wire-up & validation

- [ ] 4.1 Run `openspec validate roadmap-v2-perplexity-integration
  --strict` and confirm exit 0. Fix any delta-header or scenario-format
  errors.
  **Dependencies**: 3.2, 2.3, 1.2
- [ ] 4.2 Run a manual walkthrough: pick three phases from the new
  roadmap (one perplexity-new like P4 observability, one folded-in like
  P2 memory-architecture that combines §8.1 with old P3, one carried
  forward like P18 railway-deployment). For each, verify the row's
  source/perplexity citation is accurate against `design.md` and
  `docs/perplexity-feedback.md`.
  **Dependencies**: 4.1
- [ ] 4.3 Update the "Current Status" / "What's Not Yet Wired" note at
  the top of `CLAUDE.md` if it references the old P-numbering. (Only if
  stale references are found; skip otherwise.)
  **Dependencies**: 4.2

## Phase 5 — Session log and archival handoff

- [ ] 5.1 Append Plan-phase session log entry per `/plan-feature` Step
  11.5 (already handled by the skill; listed here for completeness).
  **Dependencies**: 4.3
- [ ] 5.2 After archival of this change, the first downstream phase
  (P1.5 bootstrap-fixes) will be invoked via `/plan-feature
  bootstrap-fixes`. No work for *this* proposal beyond archival.
  **Dependencies**: 5.1
