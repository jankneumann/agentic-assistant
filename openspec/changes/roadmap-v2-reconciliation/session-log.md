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

---

## Phase: Plan Iteration 2 (2026-04-13)

**Agent**: claude-code (Opus 4.6) | **Session**: `/iterate-on-plan`
(technical-review follow-up)

### Context

The Iteration 1 review was OpenSpec-consistency-focused. A user-directed
second dispatch (`review-prompt-technical.md`) instructed vendors to
apply the classification rule to every roadmap phase, evaluate DAG
edges for functional correctness, check perplexity §§1–§8 coverage,
and find stale P-numbering in live docs. Codex (6 findings) and
Gemini (6 findings) converged on four substantive issues plus two
minor ones.

### Decisions

1. **Broaden criterion 2** to cover all actionable items in
   `docs/perplexity-feedback.md` §§1–§8, not just §8. Codex, Gemini,
   and the primary reviewer agreed that P1.7 `bootstrap-fixes` (which
   implements §7 hygiene, not §8) fell through to criterion 3 under
   the iteration-1 wording — a weakness in the classification. The
   broadened text ("an actionable item in any section of
   `docs/perplexity-feedback.md` — covering §§1–§8") cleanly covers
   P1.7 as a phase via criterion 2 and removes the need for criterion
   3 to be load-bearing for that case.
2. **Redraw the dependency graph as functional-only**. Iteration 1's
   chain `P1 → P1.5 → P1.6 → P1.7 → everything below` encoded
   chronology as hard prerequisites. The replacement graph shows
   P1.5/P1.6 and P1.7 as sibling branches off P1, and P1.7 only gates
   the phases that need its specific §7 fixes (P2 for §7.2, P3 for
   §7.1/§7.4, P11 for §7.3, P16 for §7.1/§7.4). P4 and P10 are
   independent of P1.7. Principle added to the guiding-principles
   section: "edges represent functional prerequisites, not
   chronological or stylistic preference."
3. **Add `Kind` column to the phase-sequence table**. Separates
   `phase` rows from `non-phase (spec-sync)` rows visually without
   requiring a separate addenda section. P1.6 is now the only
   `non-phase` row; all others are `phase`.
4. **Expand P12 scope to include `delegation/router.py`**. Gemini and
   Codex both flagged that §5's P1-priority router was silently
   dropped from the v2 roadmap. P12's description now explicitly
   mentions the router; its Perplexity § column adds "§5 P1".
5. **Retire stale P-numbering in CLAUDE.md / README.md**. Replace
   `P2`/`P3`/`P4`/`P5`/`P6`/`P1–P10` with stable change-ids in
   `CLAUDE.md:39,42,64,77,101–111` and `README.md:45–46,53`. The
   single remaining `P1` reference in CLAUDE.md:41 is a factual
   historical note about the archived bootstrap phase — left as-is.
6. **Decouple criterion 3 from self-reference** (Gemini F). Old
   wording was "promoted by authoring judgment and recorded in the
   roadmap table" — circular, since the requirement elsewhere asserts
   that every phase change is in the table. New wording: "promoted by
   authoring judgment based on architectural or behavioral impact"
   — removes the recording-constitutes-classification loop.
7. **Defer `Purpose` follow-up tracking to plan-roadmap run** (Codex
   F, escalate). Codex flagged that the Purpose cleanup was filed as
   "follow-up" without any tracking artifact. Rather than create a
   stub OpenSpec change or a coordination-MCP issue now, defer the
   decision to the `/plan-roadmap` run that follows iteration 2 —
   which may legitimately absorb the Purpose cleanup into a generated
   roadmap item.

### Alternatives Considered

- **Keep criterion 2 as `§8 only` and rely on criterion 3 for P1.7**:
  rejected — criterion 3 is explicitly the "residual for edge cases
  that don't fit 1–2"; having a documented priority-§7 phase like
  P1.7 fall through to it weakens the classification for every later
  reviewer who tries to apply the rule.
- **Drop P1.6 from the roadmap entirely** (make non-phase changes
  invisible): rejected — its chronological tie to P1.5 is load-bearing
  for reviewers tracing "what reconciled the test-privacy-boundary
  validation drift." The `Kind` column restores visibility-honesty
  without removing the row.
- **Split `delegation/router.py` into its own phase** (e.g., P11.5):
  rejected — the router and delegation-context share enough
  implementation surface (both depend on memory snippets, both touch
  `DelegationSpawner`) that keeping them in one phase matches the
  expected work boundary. If P12 grows too large later, splitting is
  cheap.
- **Create a P1.8 Purpose cleanup phase now**: rejected — Purpose
  cleanup is admin tooling, not a roadmap phase; filing it into the
  phase table inflates the phase count with non-project-work.

### Trade-offs

- Accepted **mixed-case DAG** (some edges are simple linear, others
  branch) over **layered tier view** (pure graph with explicit layers).
  The mixed form is easier to read as a text diagram; a layered view
  would be more formally useful but harder to maintain in markdown.
- Accepted **criterion 2 covers §§1–§8** (broad) over **enumerate
  phase-eligible sections** (narrower, e.g., "§1–§5 and §8"). The
  broad form absorbs edge cases like a future perplexity-style review
  with different section structure; the narrow form is more precise
  but brittle.
- Accepted **postpone Purpose-cleanup tracking to plan-roadmap**
  (escalate finding deferred) over **create concrete follow-up now**.
  `/plan-roadmap` will read `docs/perplexity-feedback.md` and produce
  a structured DAG; if Purpose cleanup appears there, no separate
  artifact is needed.

### Open Questions

- [ ] `/plan-roadmap` may produce a `roadmap.yaml` whose DAG
      contradicts this iteration's hand-redrawn markdown DAG. In that
      case, the generated artifact should be considered authoritative
      and the markdown DAG a derived view — but this isn't settled yet.
- [ ] Whether the `Kind` column should be formally specified in the
      `tooling-roadmap` spec or left as a roadmap-markdown convention.
      Deferred; current spec doesn't mandate a column list.

### Findings Addressed

From the technical dispatch (codex + gemini, consolidated with primary
reviewer):

- F-T1 (HIGH/correctness): criterion 2 too narrow (§8 only) — **fixed**
  via broadening to §§1–§8.
- F-T2 (HIGH/correctness): DAG encodes chronology as hard edges — **fixed**
  via functional-only DAG redraw with explicit principle.
- F-T3 (MEDIUM/architecture): P1.6 visual mismatch — **fixed** via
  `Kind` column.
- F-T4 (HIGH/spec_gap): `delegation/router.py` dropped from coverage —
  **fixed** via P12 scope expansion.
- F-T5 (MEDIUM/compatibility): CLAUDE.md + README.md stale P-numbering
  — **fixed** via change-id replacement.
- F-T6 (MEDIUM/architecture, escalate): Purpose follow-up not tracked
  — **deferred** to `/plan-roadmap` run.
- F-T7 (LOW/correctness): criterion 3 circularity — **fixed** via
  decoupled wording.

`openspec validate --strict` passes after all edits.
