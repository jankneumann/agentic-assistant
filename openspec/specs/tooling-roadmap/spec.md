# tooling-roadmap Specification

## Purpose
TBD - created by archiving change roadmap-v2-perplexity-integration. Update Purpose after archive.
## Requirements
### Requirement: Roadmap Document Authoritative

The project SHALL maintain a single canonical roadmap at
`openspec/roadmap.md` whose phase-sequence table SHALL be the
authoritative registry of *phase changes*.

An OpenSpec change SHALL be classified as a **phase change** when it
satisfies at least one of the following:

1. It introduces a new capability spec (adds a new directory under
   `openspec/specs/`), OR
2. It implements an item enumerated in `docs/agentic-assistant-bootstrap-v4.1.md`
   (a "bootstrap-v4.1 P-item") or an actionable item in any section
   of `docs/perplexity-feedback.md` (a "perplexity item" — covering
   §§1–§8: structural gaps, chief-of-staff additions, architecture
   refinements, security, implementation completeness, A2A, minor
   fixes, and ordering), OR
3. It represents a committed project milestone promoted by authoring
   judgment based on architectural or behavioral impact (used as a
   residual for changes that don't fit criteria 1–2 but reach
   milestone-level scope independently).

All other OpenSpec changes (for example: spec-sync reconciliations that
only MODIFY an existing spec's requirements to match shipped reality,
tooling or documentation edits that change no spec, meta proposals that
edit the roadmap itself) SHALL be classified as **non-phase changes**
and are non-normative with respect to the row/status invariants below.
A non-phase change MAY be listed in the roadmap table when its
chronological or dependency tie to a phase aids reviewer navigation;
if listed, it SHALL satisfy the same row invariants as a phase change.

Every row in the roadmap's phase-sequence table MUST reference a real
change-id and MUST carry a `Status` value drawn from the set defined by
`Requirement: Phase Status Lifecycle`. Conversely, every *phase change*
— archived, in-progress, or pending — MUST appear as a row; the row
SHALL NOT be deleted when the phase archives.

#### Scenario: Every phase change has a roadmap row

- **WHEN** an OpenSpec change is classified as a phase change per the
  criteria in this requirement body
- **THEN** the change-id SHALL appear as a row in the roadmap's
  phase-sequence table
- **AND** the row's `Status` SHALL track the change's lifecycle
  (`pending` → `in-progress` → `archived`)

#### Scenario: Listed non-phase change still follows row invariants

- **WHEN** a non-phase change is listed in the roadmap table by
  authoring choice (e.g., a spec-sync that reconciles a just-archived
  phase, included for chronological clarity)
- **THEN** its row SHALL have a unique change-id, a valid `Status`
  value, and SHALL be retained — not deleted — when the change archives

#### Scenario: Every roadmap row references a real change-id

- **WHEN** a row exists in the roadmap's phase-sequence table with a
  non-empty `Change ID` column
- **THEN** either `openspec/changes/<change-id>/` SHALL exist on disk
  (for pending or in-progress rows), or
  `openspec/changes/archive/YYYY-MM-DD-<change-id>/` SHALL exist on
  disk (for archived rows, where `YYYY-MM-DD` is the archive date in
  ISO-8601 format)
- **AND** a row with an empty or placeholder change-id SHALL NOT be
  considered a binding registration

#### Scenario: Archived phase changes remain listed

- **WHEN** a phase change transitions to `archived` and its directory
  moves to `openspec/changes/archive/`
- **THEN** the corresponding row in the roadmap's phase-sequence table
  SHALL have `Status = archived`
- **AND** the row SHALL NOT be deleted from the table

### Requirement: Phase Status Lifecycle

Each roadmap phase SHALL progress through exactly three statuses —
`pending`, `in-progress`, `archived` — in that order. The roadmap
document MUST reflect the current status of every phase.

#### Scenario: Status transitions forward only

- **WHEN** a phase's status is updated
- **THEN** the new status SHALL be `pending → in-progress` or
  `in-progress → archived`
- **AND** a phase MUST NOT transition backward (e.g., `archived →
  pending`) without a dedicated follow-up proposal that documents the
  reversion rationale

#### Scenario: In-progress marker aligns with proposal directory

- **WHEN** a phase's status in the roadmap is `in-progress`
- **THEN** a directory `openspec/changes/<change-id>/` SHALL exist
  containing at minimum a `proposal.md`

### Requirement: Dependency Graph Representation

The roadmap SHALL include a "Dependency graph" section expressing the
prerequisites each phase has on earlier phases. Each phase's prerequisite
set MUST be a subset of the other phases listed in the roadmap.

#### Scenario: Prerequisites reference real phases

- **WHEN** the dependency graph lists phase B as depending on phase A
- **THEN** phase A SHALL appear in the roadmap's phase sequence table
- **AND** phase A's status SHALL be `archived` before phase B's status
  may transition to `in-progress`

#### Scenario: Graph is acyclic

- **WHEN** the dependency graph is interpreted as a directed graph (edges
  = "depends on")
- **THEN** the graph MUST be acyclic — no phase may transitively depend
  on itself

### Requirement: Provenance Attribution

Every roadmap phase SHALL include columns or annotations indicating its
source — the originating document (e.g., bootstrap-v4.1 P-number,
perplexity feedback § reference, or "new" when neither applies) — so
that reviewers can trace each phase back to its motivating analysis.

#### Scenario: Phase sourced from perplexity feedback

- **WHEN** a phase's scope is derived from the perplexity review document
- **THEN** the roadmap row SHALL cite the perplexity section in a
  "Perplexity §" column or equivalent annotation
- **AND** `docs/perplexity-feedback.md` SHALL exist in the repository as
  the canonical reference for those citations

#### Scenario: Phase carried forward from prior roadmap

- **WHEN** a phase's scope is carried forward from the pre-v2 roadmap
- **THEN** the roadmap row SHALL cite the original P-number (e.g.,
  "original P4") in its Source column

