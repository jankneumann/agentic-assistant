# memory-policy

## MODIFIED Requirements

### Requirement: MemoryPolicy Protocol

The system SHALL define a `MemoryPolicy` runtime-checkable Protocol
with the methods `resolve(persona: PersonaConfig, harness_name: str) →
MemoryConfig`, `export_memory_context(persona: PersonaConfig) → str`,
`async get_recent_snippets(persona, role, *, limit: int = 10) →
list[str]`, and `async record_interaction(persona, role, *,
user_message: str, response: str) → None`.

`get_recent_snippets` is async at the protocol level (owner review
verdict C8, 2026-07-16): consumers on async paths — SDK harness prompt
composition at `create_agent` time — MUST await it directly on the
running event loop, and synchronous callers (host-harness export, CLI
export) MUST bridge at their own edge rather than relying on a
sync-to-async bridge inside policy implementations. It returns up to
`limit` short memory snippets for prompt prepend; implementations MUST
degrade to `[]` on backend failure rather than raising.
`record_interaction` persists a completed turn to the policy's backend
(best effort); policies without a per-turn write path MUST implement
it as a no-op.

#### Scenario: Stub implementation satisfies Protocol

- **WHEN** a class implements `resolve`, `export_memory_context`,
  `get_recent_snippets`, and `record_interaction` with the correct
  signatures
- **THEN** `isinstance(instance, MemoryPolicy)` MUST return `True`

#### Scenario: Built-in policies satisfy the extended Protocol

- **WHEN** `FileMemoryPolicy`, `PostgresGraphitiMemoryPolicy`, or
  `HostProvidedMemoryPolicy` is instantiated
- **THEN** `isinstance(instance, MemoryPolicy)` MUST return `True`

#### Scenario: Snippet retrieval is awaited on the async hot path

- **WHEN** an SDK harness composes its prompt inside async
  `create_agent`
- **THEN** `get_recent_snippets` MUST be awaited directly on the
  running event loop with no intermediate sync-to-async bridge

## ADDED Requirements

### Requirement: MemoryManager Recent Snippets

The system SHALL provide an async
`MemoryManager.get_recent_snippets(persona, role, limit=10)` method in
`core/memory.py` returning at most `limit` short strings composed from
two buckets: *durable* snippets (rows from the `memory` table ordered
by `updated_at` DESC, then `preferences` rows ordered by `confidence`
DESC, then Graphiti semantic search results for `role` when a Graphiti
client is configured) and *recent* snippets (rows from the
`interactions` table ordered by `created_at` DESC, rendered as
`[role] summary`). Durable snippets receive the ceiling half of
`limit`; recent snippets fill the remainder; when either bucket
under-fills, the other MUST backfill up to `limit`. All three Postgres
reads MUST be limited to at most `limit` rows. The method MUST be
instrumented with `trace_memory_op(op="snippets")` and MUST NOT emit a
separate span for the internal Graphiti call.

#### Scenario: Happy path mixes durable and recent snippets

- **WHEN** `get_recent_snippets(persona, role, limit=10)` is awaited
  with at least one `memory` row, one `preferences` row, and one
  `interactions` row present
- **THEN** the returned list MUST contain a snippet derived from each
  of the three tables
- **AND** the list length MUST NOT exceed 10

#### Scenario: Empty database yields empty list

- **WHEN** `get_recent_snippets(persona, role)` is awaited and all
  three tables have no rows for the persona and Graphiti is not
  configured
- **THEN** it MUST return `[]` without raising

#### Scenario: Budget split between durable and recent

- **WHEN** `get_recent_snippets(persona, role, limit=4)` is awaited
  with 10 `memory` rows and 10 `interactions` rows available
- **THEN** exactly 2 durable snippets and 2 interaction snippets MUST
  be returned

#### Scenario: Recent bucket backfills when durable is scarce

- **WHEN** `get_recent_snippets(persona, role, limit=4)` is awaited
  with no durable rows and 10 `interactions` rows available
- **THEN** 4 interaction snippets MUST be returned

#### Scenario: Graphiti failure degrades to Postgres-only snippets

- **WHEN** `get_recent_snippets(persona, role)` is awaited, the
  Graphiti client is non-None, and its `search` call raises a
  connection error
- **THEN** the Postgres-derived snippets MUST still be returned
  without raising
- **AND** a `logging.WARNING`-level message including the persona name
  MUST be emitted

### Requirement: PostgresGraphitiMemoryPolicy Live Snippet Retrieval

The system SHALL implement
`PostgresGraphitiMemoryPolicy.get_recent_snippets(persona, role, *,
limit=10)` as an async method that awaits
`MemoryManager.get_recent_snippets` directly on the caller's event
loop, with no intermediate sync-to-async bridge (owner review verdict
C8, 2026-07-16). Any retrieval failure MUST degrade to `[]` with a
`logging.WARNING`-level message including the persona name — a down
memory backend MUST NOT break agent construction.

#### Scenario: Returns manager snippets

- **WHEN** `get_recent_snippets(persona, role, limit=5)` is awaited
  and the manager returns `["a", "b"]`
- **THEN** the call MUST return `["a", "b"]`
- **AND** the manager MUST be awaited with the persona name, the role
  name, and `limit=5`

#### Scenario: Backend failure degrades to empty list

- **WHEN** the underlying manager call raises a connection error
- **THEN** `get_recent_snippets` MUST return `[]`
- **AND** a `logging.WARNING`-level message including the persona name
  MUST be emitted

### Requirement: FileMemoryPolicy Recent Snippets

The system SHALL implement
`FileMemoryPolicy.get_recent_snippets(persona, role, *, limit=10)` as
an async method returning bounded excerpts of the persona's
`memory.md` content (`persona.memory_content`). The content MUST be split into `## `
sections (content before the first heading, or heading-free content,
forms a single section) and returned most-recent-first, treating later
sections as more recent. The result MUST contain at most `limit`
sections and at most 4000 total characters, truncating the section
that crosses the budget.

#### Scenario: Empty memory content yields empty list

- **WHEN** `persona.memory_content` is empty or missing
- **THEN** `get_recent_snippets` MUST return `[]`

#### Scenario: Sections returned most recent first

- **WHEN** `memory_content` contains sections `## Oldest`, `## Middle`,
  `## Newest` in document order
- **THEN** the first returned snippet MUST be the `## Newest` section
  and the last MUST be the `## Oldest` section

#### Scenario: Limit and character budget are enforced

- **WHEN** `memory_content` contains more than `limit` sections or
  more than 4000 characters of section text
- **THEN** at most `limit` snippets MUST be returned
- **AND** the total character count across snippets MUST NOT exceed
  4000

### Requirement: Post-Turn Interaction Capture

The system SHALL implement `record_interaction` on all built-in
policies. `PostgresGraphitiMemoryPolicy.record_interaction` MUST
delegate to `MemoryManager.store_interaction` with the persona name,
the role name, a whitespace-normalized summary of the form
`user: <excerpt> | assistant: <excerpt>` (each excerpt capped at 240
characters), and `metadata={"source": "post_turn_capture"}`; backend
exceptions MUST propagate to the caller (the harness capture helper
owns swallowing). `FileMemoryPolicy.record_interaction` and
`HostProvidedMemoryPolicy.record_interaction` MUST be no-ops.

#### Scenario: Postgres policy stores a bounded summary

- **WHEN** `record_interaction(persona, role, user_message=U,
  response=R)` is awaited on `PostgresGraphitiMemoryPolicy`
- **THEN** `MemoryManager.store_interaction` MUST be awaited once with
  the persona name, role name, a summary containing excerpts of both
  `U` and `R`, and `metadata={"source": "post_turn_capture"}`
- **AND** the summary MUST NOT exceed the 240-character-per-side cap
  plus fixed formatting

#### Scenario: Backend errors propagate from the policy

- **WHEN** the underlying `store_interaction` raises a connection error
- **THEN** `record_interaction` MUST let the exception propagate

#### Scenario: File policy capture is a no-op

- **WHEN** `record_interaction(...)` is awaited on `FileMemoryPolicy`
- **THEN** it MUST return `None` without writing anywhere
