# tooling-roadmap — spec delta

## MODIFIED Requirements

### Requirement: Roadmap Document Authoritative

The project SHALL maintain a single canonical roadmap at
`openspec/roadmap.md` whose phase-sequence table SHALL be the
authoritative registry of *phase changes* — the work units that advance
the project toward its bootstrap-v4.1 and perplexity-§8 goals. Meta,
tooling, and spec-sync OpenSpec changes (changes that are not phases,
e.g., a change that only updates the roadmap or an existing spec) MAY
appear in the roadmap table when their chronological or dependency
context aids review, but SHALL NOT be required to appear.

Every row in the roadmap's phase-sequence table MUST reference a real
change-id and MUST carry a `Status` value drawn from the set defined by
`Requirement: Phase Status Lifecycle`. Conversely, every *phase change*
— archived, in-progress, or pending — MUST appear as a row; the row
SHALL NOT be deleted when the phase archives.

#### Scenario: Every phase change has a roadmap row

- **WHEN** an OpenSpec change is introduced that represents a planned
  phase of project work (for example: a new capability introduction, a
  bootstrap-v4.1 P-item, a perplexity §8 item)
- **THEN** the change-id SHALL appear as a row in the roadmap's
  phase-sequence table
- **AND** the row's `Status` SHALL track the change's lifecycle
  (`pending` → `in-progress` → `archived`)

#### Scenario: Non-phase changes are not required to have a row

- **WHEN** an OpenSpec change exists that is not a phase — it updates
  an existing spec (spec-sync), modifies tooling or documentation
  (meta/tooling), or reconciles prior phase output
- **THEN** the change SHALL NOT be required to appear in the roadmap
  table
- **AND** if the author chooses to list it for chronological or
  review context, the row SHALL still follow all other roadmap
  invariants (unique change-id, valid `Status`, row retained on archive)

#### Scenario: Every roadmap row references a real change-id

- **WHEN** a row exists in the roadmap's phase-sequence table with a
  non-empty `Change ID` column
- **THEN** either `openspec/changes/<change-id>/` or
  `openspec/changes/archive/<date-prefix>-<change-id>/` SHALL exist on
  disk
- **AND** a row with an empty or placeholder change-id SHALL NOT be
  considered a binding registration

#### Scenario: Archived phase changes remain listed

- **WHEN** a phase change transitions to `archived` and its directory
  moves to `openspec/changes/archive/`
- **THEN** the corresponding row in the roadmap's phase-sequence table
  SHALL have `Status = archived`
- **AND** the row SHALL NOT be deleted from the table
