# tooling-roadmap Specification

## Purpose
TBD - created by archiving change roadmap-v2-perplexity-integration. Update Purpose after archive.
## Requirements
### Requirement: Roadmap Document Authoritative

The project SHALL maintain a single canonical roadmap at
`openspec/roadmap.md` that SHALL be the authoritative ordering of all
planned OpenSpec phases. Every non-archived phase referenced by
downstream tooling (such as `/plan-feature`, `/autopilot`, session logs)
MUST appear in the roadmap's phase sequence table with a stable change-id
and a status value.

#### Scenario: Every in-progress change has a roadmap row

- **WHEN** an OpenSpec change exists under `openspec/changes/<change-id>/`
  (not in `archive/`)
- **THEN** a row in the `openspec/roadmap.md` phase sequence table SHALL
  have `Change ID` equal to `<change-id>` and `Status` equal to either
  `pending` or `in-progress`

#### Scenario: Archived changes remain listed with archived status

- **WHEN** a change is moved to `openspec/changes/archive/`
- **THEN** the roadmap row for that change-id SHALL have `Status` equal
  to `archived`
- **AND** the row SHALL NOT be deleted from the roadmap table

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

