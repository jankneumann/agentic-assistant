# memory-policy Specification (delta)

## ADDED Requirements

### Requirement: MemoryManager Preference Upsert

The system SHALL provide an async
`MemoryManager.store_preference(persona, category, key, value,
confidence=0.5)` method in `core/memory.py` that upserts one
`preferences` row on the `(persona, category, key)` unique constraint
(updating `value`, `confidence`, and `updated_at` on conflict —
mirroring the `store_fact` upsert pattern). The method MUST reject
non-JSON-serializable values and a `confidence` outside `[0, 1]` with
a `ValueError`, and MUST be instrumented with
`trace_memory_op(op="preference_write")` using the preference `key`
as the span target. It exists as the write surface behind applied
P28 `preference` proposals (distilled preferences never bypass the
memory layer).

#### Scenario: Preference upserts on the unique constraint

- **WHEN** `store_preference("personal", "style", "tone", "concise",
  confidence=0.7)` is awaited twice
- **THEN** exactly one row exists for `(personal, style, tone)` with
  the latest value and confidence

#### Scenario: Invalid inputs are rejected

- **WHEN** a non-serializable value or a confidence of `1.5` is given
- **THEN** a `ValueError` MUST be raised and nothing stored

#### Scenario: Preference write emits its trace op

- **WHEN** `store_preference` is awaited
- **THEN** `trace_memory_op` MUST be called once with
  `op="preference_write"` and the preference key as target
