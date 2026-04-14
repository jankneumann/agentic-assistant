# Tasks — roadmap-v2-reconciliation

Docs + spec change. No production code or new tests. Validation is via
`openspec validate --strict` and manual review of roadmap row accuracy.

## Phase 1 — Spec MODIFY

- [x] 1.1 Write delta: author
  `openspec/changes/roadmap-v2-reconciliation/specs/tooling-roadmap/spec.md`
  with a `## MODIFIED Requirements` section containing the fully-rewritten
  "Roadmap Document Authoritative" requirement. The rewrite SHALL (a)
  define `phase change` via three operational criteria in the requirement
  body (per D1), and (b) provide four scenarios: "Every phase change has
  a roadmap row", "Listed non-phase change still follows row invariants",
  "Every roadmap row references a real change-id" (using `YYYY-MM-DD-`
  archive-date format), and "Archived phase changes remain listed".
  **Spec scenarios**: see above
  **Contracts**: N/A
  **Design decisions**: D1, D2
  **Dependencies**: None

- [x] 1.2 Validate: `openspec validate roadmap-v2-reconciliation --strict`
  exits 0.
  **Dependencies**: 1.1

## Phase 2 — Roadmap edit

- [x] 2.1 Edit `openspec/roadmap.md` phase-sequence table:
  - Insert new row `P1.5 test-privacy-boundary` (archived 2026-04-13).
    Perplexity §: "—". Source: "new (IR hygiene from P1 validation)".
  - Insert new row `P1.6 sync-test-privacy-boundary-spec` (archived
    2026-04-13). Perplexity §: "—". Source: "spec-sync follow-up of P1.5".
  - Rename existing `P1.5 bootstrap-fixes` to `P1.7 bootstrap-fixes`
    (status + content unchanged).
  **Design decisions**: D3, D4
  **Dependencies**: 1.2

- [x] 2.2 Edit `openspec/roadmap.md` Dependency graph:
  - Replace the `P1 (archived) └─→ P1.5 bootstrap-fixes` edge with the
    chain: `P1 (archived) └─→ P1.5 test-privacy-boundary (archived) └─→
    P1.6 sync-test-privacy-boundary-spec (archived) └─→ P1.7
    bootstrap-fixes (pending; unblocks everything below)`.
  - Downstream edges that pointed at old P1.5 now point at P1.7.
  **Design decisions**: D3
  **Dependencies**: 2.1

- [x] 2.3 Spot-check: verify all other references in `roadmap.md` (Phase
  execution playbook, Cross-cutting themes, Out-of-scope section) are
  still consistent after the renumber. No other edits expected.
  **Dependencies**: 2.2

## Phase 3 — Wire-up & validation

- [x] 3.1 Re-run `openspec validate roadmap-v2-reconciliation --strict`
  after the roadmap edit lands. Exit 0 required.
  **Dependencies**: 2.3

- [x] 3.2 Manual walkthrough: confirm the narrowed `Roadmap Document
  Authoritative` requirement no longer self-violates (the
  `roadmap-v2-reconciliation` directory exists but is itself a
  non-phase change; it should not require a roadmap row under the
  narrowed scope).
  **Dependencies**: 3.1

## Phase 4 — Session log and archival handoff

- [x] 4.1 Append Plan-phase session log entry documenting the
  parallel-review-plan findings and their disposition.
  **Dependencies**: 3.2

- [x] 4.2 After this change archives, the `Purpose` placeholder and the
  P2 self-violation will be fully resolved. The next downstream phase
  to plan is P1.7 `bootstrap-fixes`.
  **Dependencies**: 4.1
