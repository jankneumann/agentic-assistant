# Design — roadmap-v2-reconciliation

## Scope recap

This is a **docs + spec** change. No production code, no new tests, no
dependency updates. Artifacts touched:

1. `openspec/specs/tooling-roadmap/spec.md` — MODIFY one requirement +
   update Purpose (via `openspec/changes/roadmap-v2-reconciliation/specs/tooling-roadmap/spec.md`
   at archive time)
2. `openspec/roadmap.md` — add two rows, renumber one, adjust DAG
3. This change's own proposal / design / tasks / session-log

## Decisions

### D1: Narrow by reference, not by exclusion list

**Decision**: The MODIFY of `Requirement: Roadmap Document Authoritative`
phrases the invariant as "the roadmap table is the registry of phase
changes; every row references a real change-id directory; every phase
change has a row." It does *not* enumerate a list of exempt non-phase
change-kinds (meta, tooling, spec-sync).

**Rationale**: Enumeration is brittle — new kinds of non-phase work
(e.g., a future ADR-style change) would each require a spec edit. The
reference-based definition (*phase = "in the roadmap table"*) lets the
roadmap itself decide what is a phase. This matches how bootstrap-v4.1
P-numbers and perplexity §8 items were promoted into the table: an
authoring decision, not a spec-enforced classifier.

**Counterpoint considered**: Reference-based definition has a
tautological flavor ("a phase is what's in the table of phases"). We
accept the tautology because it's load-bearing: the roadmap is the
single source of truth for phase identity. Any secondary definition
would drift.

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

### D5: Fix the `Purpose` placeholder inline

**Decision**: Include `Purpose` replacement in the same MODIFY delta,
not a separate change.

**Rationale**: Trivial cleanup bundled with the spec's first real edit
after archival. The `TBD - created by archiving change...` text was
inserted by `openspec archive` as a placeholder and should not persist
past the first follow-up proposal that touches the spec.

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
