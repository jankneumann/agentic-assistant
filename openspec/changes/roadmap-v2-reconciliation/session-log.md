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

---

## Phase: Plan Iteration 1 (2026-04-13)

**Agent**: claude-code (Opus 4.6) | **Session**: `/iterate-on-plan`

### Decisions

1. **Drop `Purpose` cleanup from scope** (reverses D5). Three of three
   vendor reviewers (self, codex, gemini) independently flagged that
   OpenSpec delta format has no mechanism to update `Purpose` from a
   change delta; evidence is 5+ specs in `openspec/specs/` carrying
   identical TBD placeholders. Spot-cleaning one spec is out of
   proportion; filed as a repo-wide follow-up.
2. **Redefine "phase change" by operational criteria** (evolves D1).
   Earlier draft used a reference-based tautology ("a phase is what's
   in the table"). Vendor reviewers flagged that this left authors
   with no decision rule. The revised requirement body enumerates
   three classification criteria: (a) introduces a new capability
   spec, (b) implements a bootstrap-v4.1 P-item or perplexity §8 item,
   (c) represents a committed milestone promoted by authoring judgment.
   All other changes are non-phase by default.
3. **Restructure the former "Non-phase changes are not required" scenario**
   as a positive obligation: "Listed non-phase change still follows row
   invariants." Negative-permissive phrasing ("SHALL NOT be required")
   is atypical for OpenSpec scenarios and untestable as written.
4. **Tighten `<date-prefix>` to `YYYY-MM-DD-`** in the "Every roadmap row
   references a real change-id" scenario. Low-criticality finding
   closed cheaply alongside the other rewrites.

### Alternatives Considered

- **Keep D5 + add manual Purpose edit task + expand work-packages scope**:
  rejected — expands blast radius across `openspec/specs/**` for
  marginal benefit that doesn't survive archival in isolation.
- **Keep reference-based phase definition** (original D1): rejected —
  author ambiguity is a real, documented review concern.
- **Enumerate exempt non-phase kinds instead of defining phase
  criteria**: rejected — list-of-exemptions is brittle as new change
  kinds emerge; criterion-based classification scales.

### Trade-offs

- Accepted **criterion-based definition** (three enumerated categories
  of what qualifies as a phase) over **reference-based definition**
  (table membership is self-defining). Cost: future changes that
  don't fit criteria 1-2 rely on criterion 3's "authoring judgment"
  escape hatch. Benefit: reviewers reading the spec alone can classify
  changes without cross-referencing.
- Accepted **TBD Purpose placeholder survives in tooling-roadmap spec**
  (matches 5+ other specs) over **inline Purpose cleanup** (requires
  scope expansion and manual post-archive edit). Cost: spec carries
  a cosmetic placeholder until repo-wide cleanup. Benefit: this
  change stays within its scope.

### Open Questions

- [ ] Follow-up: repo-wide `TBD Purpose` cleanup proposal — manual
      pass across 5+ specs, OR extend OpenSpec delta format.
- [ ] Next iteration or vendor re-review may surface additional
      clarity concerns with criterion 3's "authoring judgment" escape.

### Context

Addressed iterate-on-plan findings at or above the medium threshold:

- F#1 (HIGH/correctness): dropped Purpose scope — closed
- F#2 (MEDIUM/spec_gap): added operational criteria to requirement body
  — closed
- F#3 (MEDIUM/correctness): restructured negative-permissive scenario
  as positive obligation — closed
- F#4 (MEDIUM/architecture): resolved via F#2's criteria (one fix, two
  findings closed)
- F#5 (LOW/spec_gap, date-prefix format): fixed cheaply — closed

Remaining below-threshold findings deferred: F#6 (renumbering stale
archive refs — accept, non-functional), F#7 (no automated drift
detection — accept, inherited design choice), F#8 (archive-date format
in scenario — accept), F#9 (scope.deny semantics — accept, resolved
as a side-effect of F#1 path (a)). `openspec validate --strict` passes.
