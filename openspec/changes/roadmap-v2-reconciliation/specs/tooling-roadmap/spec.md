# tooling-roadmap — spec delta

## MODIFIED Requirements

### Requirement: Roadmap Document Authoritative

The project SHALL maintain a single canonical roadmap at
`openspec/roadmap.md` whose phase-sequence table SHALL be the
authoritative registry of *phase changes*.

An OpenSpec change SHALL be classified as a **phase change** when it
satisfies at least one of the following:

1. It introduces a new capability spec (adds a new directory under
   `openspec/specs/`), OR
2. It implements an item enumerated in `docs/agentic-assistant-bootstrap-v4.1.md`
   (a "bootstrap-v4.1 P-item") or in `docs/perplexity-feedback.md` §8
   ("perplexity §8 item"), OR
3. It represents a committed project milestone explicitly promoted by
   authoring judgment and recorded in the roadmap table.

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
