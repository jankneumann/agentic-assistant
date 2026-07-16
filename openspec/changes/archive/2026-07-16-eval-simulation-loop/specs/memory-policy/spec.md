# memory-policy Specification (delta)

## ADDED Requirements

### Requirement: MemoryManager Interaction Listing

The system SHALL provide an async
`MemoryManager.list_interactions(persona, role=None, limit=50)` method
in `core/memory.py` returning the persona's stored interactions as
JSON-safe dicts with keys `id`, `role`, `summary`, `created_at`
(ISO-8601 string or `None`), and `metadata` (dict, defaulting to
`{}`), ordered by `created_at` descending and limited to at most
`limit` rows. When `role` is provided, only interactions recorded
under that role SHALL be returned. A non-positive `limit` SHALL return
an empty list without querying the database. The method exists to
back `assistant export-eval-dataset` (P27 eval-simulation-loop
trace→dataset export).

#### Scenario: Returns JSON-safe dicts newest first

- **WHEN** `list_interactions("personal", limit=10)` is awaited and
  the `interactions` table has rows for that persona
- **THEN** each returned item MUST be a dict with keys `id`, `role`,
  `summary`, `created_at`, and `metadata`
- **AND** `created_at` MUST be an ISO-8601 string when the stored
  value is a datetime
- **AND** results MUST be ordered by `created_at` DESC and capped at
  `limit`

#### Scenario: Role filter narrows results

- **WHEN** `list_interactions("personal", role="coder")` is awaited
- **THEN** the underlying query MUST filter on both persona and role

#### Scenario: Non-positive limit short-circuits

- **WHEN** `list_interactions("personal", limit=0)` is awaited
- **THEN** it MUST return `[]` without executing a database query
