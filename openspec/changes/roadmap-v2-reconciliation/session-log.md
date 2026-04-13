# Session log — roadmap-v2-reconciliation

---

## Phase: Plan (2026-04-13)

**Agent**: claude-code (Opus 4.6) | **Session**: `/merge-pull-requests`

### Decisions

1. **Bundle three reconciliation items in one change** (Approach A).
   Spec MODIFY (narrow scope), Purpose cleanup, roadmap row additions
   ship together. Rejected two-change split (Approach B) because the
   interim state leaves "Archived changes remain listed" violated for
   test-privacy-boundary and sync-test-privacy-boundary-spec.
2. **Narrow by reference, not by exclusion list** (D1). The spec
   phrases the invariant as "the roadmap table registers phase changes;
   every row has a change-id directory; every phase change has a row"
   rather than enumerating exempt kinds. Reference-based definition
   avoids brittle enumeration as new kinds emerge.
3. **Chronological P-numbering** (D3). Test-boundary work lands as
   P1.5 / P1.6; `bootstrap-fixes` bumps to P1.7. Rejected "keep P1.5
   bootstrap-fixes" because test-boundary has already shipped.
4. **Spec-sync CAN be a phase** (D4). The D1 narrowing creates a
   permission, not a mandate. User direction placed
   `sync-test-privacy-boundary-spec` in the roadmap table at P1.6
   because its chronological tie to P1.5 matters.
5. **Fix `Purpose` placeholder inline** (D5). Bundle the trivial
   `openspec archive`-inserted `TBD` cleanup with the first real
   follow-up edit to the spec.

### Alternatives Considered

- **Approach B (two sequential changes)**: rejected — interim state
  violates archived-remain-listed invariant.
- **Approach C (prose exemption, no spec edit)**: rejected — invalidates
  the capability's purpose; Codex P2 finding stands.
- **Enumerate `kind:` field in spec**: rejected (D1) — brittle as new
  change kinds emerge.
- **Hygiene addenda sub-table in `roadmap.md`**: rejected (D3) —
  splinters the single authoritative table.
- **P1.6/P1.7 for test-boundary, keep P1.5 bootstrap-fixes**: rejected
  (D3) — violates chronological ordering.

### Trade-offs

- Accepted **reference-based scope definition** (tautological flavor)
  over **enumerated kinds list** (brittle, drifts).
- Accepted **bundle spec + docs in one change** (larger blast radius)
  over **two sequential changes** (twice the ceremony, interim
  inconsistency).
- Accepted **permission not mandate** for spec-sync listing (D4) — the
  cost is authoring judgment per spec-sync; the benefit is preserving
  chronological clarity when spec-syncs matter.

### Open Questions

- [ ] parallel-review-plan may push back on D1's reference-based
      definition; if reviewers propose an enumerated kinds list, revisit.
- [ ] parallel-review-plan may propose separating Purpose cleanup from
      the spec scope narrowing; if so, revisit D5.

### Context

Post-merge reconciliation following PR 3 (`roadmap-v2-perplexity-integration`):
Codex review flagged two issues; one (missing `docs/perplexity-feedback.md`)
was closed in commit `25f34cd` before archive. The other (spec scope
too broad, requirement self-violates) plus the `test-privacy-boundary` /
`sync-test-privacy-boundary-spec` roadmap-row omission are the scope of
this change. Parallel-review-plan dispatch will stress-test the
narrowing decision before implementation.
