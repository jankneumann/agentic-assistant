# memory-policy Specification (delta)

## ADDED Requirements

### Requirement: MemoryManager Structured Fact and Preference Listing

The system SHALL provide async `MemoryManager.list_facts(persona,
limit=100)` and `MemoryManager.list_preferences(persona, limit=100)`
methods in `core/memory.py` returning JSON-safe dicts — facts with
keys `id`, `key`, `value`, `updated_at` (ISO-8601 string or `None`),
ordered by `updated_at` descending; preferences with keys `id`,
`category`, `key`, `value`, `confidence`, `updated_at`, ordered by
`confidence` descending — each limited to at most `limit` rows. A
non-positive `limit` SHALL return an empty list without querying the
database. The methods MUST be instrumented with
`trace_memory_op(op="fact_list")` and
`trace_memory_op(op="preference_list")` respectively. They exist as
the structured read surface behind the P26 clean-room export gateway
(the formatted `get_context` / snippet reads are unsuitable for
declassification rule evaluation).

#### Scenario: Facts listed as JSON-safe dicts newest first

- **WHEN** `list_facts("personal", limit=10)` is awaited and the
  `memory` table has rows for that persona
- **THEN** each item MUST be a dict with keys `id`, `key`, `value`,
  and `updated_at` (ISO-8601 string when the stored value is a
  datetime)
- **AND** results MUST be ordered by `updated_at` DESC and capped at
  `limit`

#### Scenario: Preferences listed by confidence

- **WHEN** `list_preferences("personal")` is awaited
- **THEN** each item MUST carry `category`, `key`, `value`, and
  `confidence`, ordered by `confidence` DESC

#### Scenario: Non-positive limit short-circuits

- **WHEN** `list_facts("personal", limit=0)` is awaited
- **THEN** it MUST return `[]` without executing a database query

### Requirement: MemoryManager Prefix-Scoped Fact Deletion

The system SHALL provide an async
`MemoryManager.delete_facts_by_prefix(persona, key_prefix)` method
that deletes every `memory` row for the persona whose key starts with
`key_prefix` (LIKE-escaped so `%`/`_` in the prefix match literally)
and returns the number of deleted rows, instrumented with
`trace_memory_op(op="fact_delete")`. An empty `key_prefix` MUST be
refused with a `ValueError` before any database access — the method
backs P26 clean-room revocation purges (imported items live under
`cleanroom/<bundle_id>/` keys) and must never be able to wipe a
persona's whole memory table by accident.

#### Scenario: Prefix delete removes matching rows and reports count

- **WHEN** `delete_facts_by_prefix("personal", "cleanroom/abc/")` is
  awaited
- **THEN** the issued statement MUST filter on both persona and the
  escaped key prefix
- **AND** the returned value MUST be the deleted row count

#### Scenario: Empty prefix is refused

- **WHEN** `delete_facts_by_prefix("personal", "")` is awaited
- **THEN** it MUST raise `ValueError` without touching the database
