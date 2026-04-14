# Design — roadmap-v2-reconciliation

## Scope recap

This is a **docs + spec** change. No production code, no new tests, no
dependency updates. Artifacts touched:

1. `openspec/specs/tooling-roadmap/spec.md` — MODIFY one requirement
   (via `openspec/changes/roadmap-v2-reconciliation/specs/tooling-roadmap/spec.md`
   at archive time)
2. `openspec/roadmap.md` — add two rows, renumber one, adjust DAG
3. This change's own proposal / design / tasks / session-log

## Decisions

### D1: Classify by operational criteria, not by table membership

**Decision**: The MODIFY of `Requirement: Roadmap Document Authoritative`
defines `phase change` via three disjunctive criteria in the requirement
body: (1) introduces a new capability spec, (2) implements a
bootstrap-v4.1 P-item or perplexity §8 item, (3) represents a committed
milestone explicitly promoted by authoring judgment. All other changes
(spec-sync, meta, tooling) are non-phase.

**Rationale**: Earlier drafting considered a *reference-based* definition
("a phase is whatever is in the roadmap table"), but iterate-on-plan
feedback (F#2, F#4) and two of three vendor reviewers flagged the
tautology: it gives no decision rule to the author, leaving classification
ambiguous. The criterion-based definition is now testable — a reviewer
reading the spec alone can classify any change without consulting prior
context. Criterion 3 preserves authoring judgment for edge cases (a
substantial hygiene change that doesn't fit 1 or 2 can still be
promoted) without leaving the default undefined.

**Counterpoint considered**: Criterion enumeration is in tension with
"don't enumerate kinds — new kinds drift the list." The rebuttal: we
enumerate what *qualifies as* a phase (three relatively stable
categories), not what is *exempt*. New change kinds default to
non-phase unless authoring judgment promotes them via criterion 3;
they don't require a spec edit.

### D2: Keep the "Archived remain listed" scenario unchanged

**Decision**: The second scenario under the MODIFIED requirement
("Archived changes remain listed with archived status") still applies
verbatim — but only to changes that *were* phase changes. A meta
proposal (like roadmap-v2-perplexity-integration itself) that was never
in the table does not earn a row when archived.

**Rationale**: Historical accuracy matters for phases (they represent
committed-to milestones). Historical accuracy for meta changes is
served by `openspec/changes/archive/` directly; no roadmap row needed.

### D3: Chronological numbering (P1.5/P1.6 for test-boundary)

**Decision**: The two test-boundary rows get P1.5 and P1.6. The
existing P1.5 (`bootstrap-fixes`) is bumped to P1.7.

**Rationale**: Test-privacy-boundary and sync-test-privacy-boundary-spec
both landed on 2026-04-13, before bootstrap-fixes has been planned.
Chronological ordering in the P-numbering aligns with the roadmap's
status lifecycle section, which reads the sequence top-to-bottom as the
temporal order of execution.

**Counterpoint considered**: Alternatives were:
- `P1.6` / `P1.7` for the test-boundary pair, keep `P1.5 bootstrap-fixes`
  (reject — violates chronological ordering; bootstrap-fixes hasn't
  happened yet but test-boundary has)
- A separate "hygiene addenda" sub-table (reject — splinters the single
  authoritative table into two)

### D4: `sync-test-privacy-boundary-spec` IS a phase (not a non-phase meta change)

**Decision**: `sync-test-privacy-boundary-spec` gets a roadmap row as
P1.6 even though it's a spec-sync (a candidate "non-phase" kind per
D1's narrowing).

**Rationale**: Spec-sync follow-ups that close drift from a just-landed
phase ARE part of that phase's story. Classifying them as non-phase
would hide their relationship to the phase they reconcile. User direction
(this session) confirms the preference for explicit chronology over
maximally-strict non-phase classification.

**Implication**: The D1 narrowing creates a *permission*, not a
*mandate*. Meta / tooling / spec-sync changes *may* be listed in the
roadmap; they aren't *required* to be. Authoring judgment decides.

### D5 (rejected): Fix the `Purpose` placeholder inline

**Decision**: **Rejected** during iterate-on-plan. `Purpose` cleanup is
removed from this change's scope.

**Rationale for rejection**: Three of three vendor reviewers (this
agent, codex, gemini) independently flagged that OpenSpec's delta
format has no mechanism to update the `Purpose` section from a change
delta — archive tooling only applies requirement-level ADDED / MODIFIED
/ REMOVED operations. Evidence: 5+ specs in `openspec/specs/`
(delegation-spawner, role-registry, extension-registry, cli-interface,
tooling-roadmap) carry identical `TBD - created by archiving change...`
placeholders that have survived multiple archival cycles. Spot-cleaning
one spec's Purpose via a manual post-archive edit is out of proportion
to the benefit and expands this change's write-scope across
`openspec/specs/**` (otherwise in `scope.deny`).

**Follow-up**: Filed as future work. A dedicated repo-wide cleanup
proposal can (a) manually update all TBD placeholders in one pass, OR
(b) extend the OpenSpec delta format to support `## Purpose` sections.

## Non-goals

- **No implementation of `bootstrap-fixes`**: that's a downstream
  proposal; this change only renumbers its placeholder row.
- **No edits to the other three requirements** (Phase Status Lifecycle,
  Dependency Graph Representation, Provenance Attribution): they're
  unaffected by the narrowing.
- **No changes to the Cross-cutting themes or Out-of-scope sections** of
  `roadmap.md`: both are correct as written in v2.
- **No `openspec` CLI enhancements**: any CI enforcement of the narrowed
  invariant is deferred to a separate proposal if warranted.

## Open questions

None at plan time. Expected parallel-review-plan findings to target:
- Whether D1's reference-based definition is robust enough
- Whether D4's "permission not mandate" is the right framing or whether
  spec-syncs should be mandated as phases when they reconcile a phase
- Whether the Purpose text belongs here or in a separate commit
