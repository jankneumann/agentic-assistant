# memory-policy Specification

## Purpose
Governs the `MemoryPolicy` protocol with its `MemoryConfig` and
`MemoryScoping` types, and the persistent memory stack behind it: the
database engine and async session factories, the Graphiti client factory,
Alembic migration infrastructure, the memory database schema, the
`MemoryManager`, and the `FileMemoryPolicy` and `PostgresGraphitiMemoryPolicy`
implementations. It exists to give each persona isolated, pluggable
conversation memory backed by its own Postgres database. Harnesses consume
policies through the capability resolver rather than touching storage
directly.
## Requirements
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

### Requirement: MemoryConfig Type

The system SHALL define a `MemoryConfig` dataclass with fields
`backend_type: str` (one of `"file"`, `"postgres"`, `"graphiti"`,
`"host_provided"`), `config: dict[str, Any]`, and
`scoping: MemoryScoping`.

#### Scenario: MemoryConfig captures backend selection

- **WHEN** a `MemoryConfig` is created with `backend_type="file"`,
  `config={"memory_files": ["./AGENTS.md"]}`
- **THEN** all fields MUST be accessible as typed attributes

### Requirement: MemoryScoping Type

The system SHALL define a `MemoryScoping` dataclass with fields
`per_persona: bool`, `per_role: bool`, and `per_session: bool`,
defaulting to `per_persona=True`, `per_role=False`,
`per_session=False`.

#### Scenario: Default scoping is per-persona only

- **WHEN** a `MemoryScoping()` is created with no arguments
- **THEN** `per_persona` MUST be `True`
- **AND** `per_role` MUST be `False`
- **AND** `per_session` MUST be `False`

### Requirement: FileMemoryPolicy Stub

The system SHALL retain `FileMemoryPolicy` as a fallback for personas
without `database_url` configured. `FileMemoryPolicy` behavior is
unchanged — it reads `persona.harnesses[harness_name].memory_files`
and returns `MemoryConfig(backend_type="file", ...)`.

#### Scenario: FileMemoryPolicy still works for file-only personas

- **WHEN** `FileMemoryPolicy().resolve(persona, "deep_agents")` is called
  with `persona.harnesses["deep_agents"]["memory_files"] == ["./CONTEXT.md"]`
- **THEN** it MUST return a `MemoryConfig` with
  `config["memory_files"] == ["./CONTEXT.md"]`

#### Scenario: FileMemoryPolicy defaults when memory_files absent

- **WHEN** `FileMemoryPolicy().resolve(persona, "deep_agents")` is called
  and `persona.harnesses["deep_agents"]` has no `memory_files` key
- **THEN** it MUST return a `MemoryConfig` with
  `config["memory_files"] == ["./AGENTS.md"]`

### Requirement: Database Engine Factory

The system SHALL provide a `create_async_engine(persona)` function in
`core/db.py` that returns a cached `AsyncEngine` per persona's
`database_url`. Engines MUST be lazily initialized on first access and
cached by URL. The cache MUST be clearable via `_clear_engine_cache()`
for test isolation.

#### Scenario: Engine created for persona with database_url

- **WHEN** `create_async_engine(persona)` is called with a persona whose
  `database_url` is `"postgresql+asyncpg://localhost/personal"`
- **THEN** it MUST return an `AsyncEngine` instance
- **AND** the engine's dialect MUST use the asyncpg driver

#### Scenario: Engine cached on second call

- **WHEN** `create_async_engine(persona)` is called twice with the same
  `database_url`
- **THEN** it MUST return the same engine instance

#### Scenario: Engine not created when database_url is empty

- **WHEN** `create_async_engine(persona)` is called with a persona whose
  `database_url` is `""`
- **THEN** it MUST raise `ValueError` with a message indicating no
  database URL configured

### Requirement: Async Session Factory

The system SHALL provide an `async_session_factory(engine)` function in
`core/db.py` that returns an `async_sessionmaker` bound to the given
engine.

#### Scenario: Session factory returns async sessionmaker

- **WHEN** `async_session_factory(engine)` is called with a valid
  `AsyncEngine`
- **THEN** it MUST return an `async_sessionmaker` that produces
  `AsyncSession` instances

#### Scenario: Session factory rejects None engine

- **WHEN** `async_session_factory(None)` is called
- **THEN** it MUST raise `ValueError`

### Requirement: Graphiti Client Factory

The system SHALL provide a `create_graphiti_client(persona)` function in
`core/graphiti.py` that returns a cached `Graphiti` client per persona's
FalkorDB configuration. Clients MUST be lazily initialized and cached.
FalkorDB host, port, password, and database MUST be read from persona
config env vars via `_env()`. The cache MUST be clearable via
`_clear_graphiti_cache()` for test isolation.

#### Scenario: Client created for persona with graphiti config

- **WHEN** `create_graphiti_client(persona)` is called with a persona
  whose `graphiti_url` is non-empty and FalkorDB env vars are set
- **THEN** it MUST return a `Graphiti` client instance using `FalkorDriver`

#### Scenario: Client cached on second call

- **WHEN** `create_graphiti_client(persona)` is called twice with the
  same persona
- **THEN** it MUST return the same client instance

#### Scenario: Client returns None when graphiti_url is empty

- **WHEN** `create_graphiti_client(persona)` is called with a persona
  whose `graphiti_url` is `""`
- **THEN** it MUST return `None`

### Requirement: Alembic Migration Infrastructure

The system SHALL provide Alembic migration infrastructure in
`src/assistant/migrations/` with an async-aware `env.py` that uses the
engine factory from `core/db.py`.

#### Scenario: Initial migration creates tables

- **WHEN** the initial migration `001_initial_memory_schema` is applied
- **THEN** the `memory`, `preferences`, and `interactions` tables MUST
  exist with all columns and constraints from the database contract

#### Scenario: Downgrade reverses initial migration

- **WHEN** the initial migration is downgraded
- **THEN** the `memory`, `preferences`, and `interactions` tables MUST
  be dropped

### Requirement: Memory Database Schema

The system SHALL define three SQLAlchemy ORM models for per-persona
memory storage: `MemoryEntry` (key-value operational state),
`Preference` (learned user preferences with confidence), and
`Interaction` (session history with role and summary).

#### Scenario: MemoryEntry stores operational state

- **WHEN** a `MemoryEntry` is created with `persona="personal"`,
  `key="active_project"`, `value={"name": "newsletter"}`
- **THEN** the record MUST be persistable and retrievable by persona + key
- **AND** `updated_at` MUST be automatically set
- **AND** a duplicate `(persona, key)` insert MUST raise an integrity error

#### Scenario: Preference stores categorized preferences

- **WHEN** a `Preference` is created with `persona="personal"`,
  `category="communication"`, `key="tone"`, `value="concise"`,
  `confidence=0.8`
- **THEN** the record MUST be queryable by persona + category
- **AND** `updated_at` MUST be automatically set on creation and update
- **AND** a duplicate `(persona, category, key)` insert MUST raise an
  integrity error

#### Scenario: Interaction stores session history

- **WHEN** an `Interaction` is created with `persona="personal"`,
  `role="researcher"`, `summary="Found 3 relevant papers"`,
  `metadata={"sources": 3}`
- **THEN** `created_at` MUST be automatically set
- **AND** `metadata` MUST default to `{}` when not provided
- **AND** records MUST be queryable by persona with time-range filtering

### Requirement: MemoryManager Class

The system SHALL provide a `MemoryManager` class in `core/memory.py`
that coordinates reads and writes across Postgres and Graphiti backends.
It MUST accept an `AsyncSession` factory and an optional `Graphiti`
client.

#### Scenario: get_context merges Postgres and Graphiti

- **WHEN** `get_context(persona, role)` is called with both backends
  available
- **THEN** the returned string MUST contain the literal substring
  `## Active Context` drawn from the `memory` table
- **AND** it MUST contain the literal substring `## Semantic Context`
  drawn from Graphiti search results
- **AND** it MUST limit Postgres reads to at most `limit` rows
  (default: 50), ordered by `updated_at` DESC

#### Scenario: get_context returns Postgres-only when Graphiti unavailable

- **WHEN** `get_context(persona, role)` is called and Graphiti client
  is `None`
- **THEN** it MUST return context containing `## Active Context` from
  Postgres only without raising
- **AND** it MUST NOT contain `## Semantic Context`

#### Scenario: get_context degrades on Graphiti connection error

- **WHEN** `get_context(persona, role)` is called, Graphiti client is
  non-None, but the Graphiti call raises a connection error
- **THEN** it MUST return Postgres-only context without raising
- **AND** it MUST emit a `logging.WARNING`-level message including the
  persona name

#### Scenario: store_fact persists to Postgres

- **WHEN** `store_fact(persona, "active_project", {"name": "newsletter"})`
  is called
- **THEN** the `memory` table MUST contain a row with that key and value
- **AND** if the key already exists, the value MUST be updated (upsert)
- **AND** `updated_at` MUST be refreshed on upsert

#### Scenario: store_fact rejects non-serializable values

- **WHEN** `store_fact(persona, key, value)` is called with a value that
  is not JSON-serializable
- **THEN** it MUST raise `ValueError` before attempting a DB write

#### Scenario: store_interaction persists to Postgres

- **WHEN** `store_interaction(persona, "researcher", "Found papers",
  metadata={"sources": 3})` is called
- **THEN** the `interactions` table MUST contain a new row with that
  role, summary, and metadata

#### Scenario: store_interaction defaults metadata

- **WHEN** `store_interaction(persona, role, summary)` is called
  without metadata
- **THEN** the `metadata` JSONB field MUST default to `{}`

#### Scenario: store_episode ingests into Graphiti

- **WHEN** `store_episode(persona, "User prefers concise replies",
  "conversation")` is called and Graphiti is available
- **THEN** the episode MUST be added via `graphiti_client.add_episode()`

#### Scenario: store_episode is no-op when Graphiti unavailable

- **WHEN** `store_episode()` is called and Graphiti client is `None`
- **THEN** the call MUST emit a `logging.WARNING`-level message that
  includes the persona name and the source argument
- **AND** it MUST return without raising

#### Scenario: store_episode degrades on Graphiti connection error

- **WHEN** `store_episode()` is called and the Graphiti client raises
  a connection error
- **THEN** the call MUST emit a `logging.WARNING`-level message and
  return without raising, equivalent to the None-client path

#### Scenario: search queries Graphiti

- **WHEN** `search(persona, "newsletter preferences")` is called with
  Graphiti available
- **THEN** it MUST return a `list[str]` where each string is the
  episode content extracted from the Graphiti result
- **AND** results MUST be limited to at most `num_results` items
  (default: 5)

#### Scenario: search returns empty when Graphiti unavailable

- **WHEN** `search(persona, query)` is called and Graphiti client is
  `None`
- **THEN** it MUST return an empty list without raising

#### Scenario: export_memory produces structured Markdown

- **WHEN** `export_memory(persona)` is called with both backends
  available and the `memory` table has at least one row
- **THEN** the output MUST contain sections `## Active Context`,
  `## Preferences`, `## Recent Interactions`, and
  `## Knowledge Graph Summary`
- **AND** the Active Context section MUST contain at least one key from
  the `memory` table
- **AND** Recent Interactions MUST include at most 100 interactions
  ordered by `created_at` DESC
- **AND** the output MUST be UTF-8 encoded ending with a single trailing
  newline

#### Scenario: export_memory omits Knowledge Graph when Graphiti unavailable

- **WHEN** `export_memory(persona)` is called and Graphiti client is
  `None`
- **THEN** the output MUST contain `## Active Context`,
  `## Preferences`, and `## Recent Interactions` sections
- **AND** it MUST NOT contain `## Knowledge Graph Summary`

### Requirement: PostgresGraphitiMemoryPolicy

The system SHALL provide a `PostgresGraphitiMemoryPolicy` class that
implements the `MemoryPolicy` protocol using `MemoryManager` as its
backend.

#### Scenario: Satisfies MemoryPolicy protocol

- **WHEN** `PostgresGraphitiMemoryPolicy` is instantiated
- **THEN** `isinstance(instance, MemoryPolicy)` MUST return `True`

#### Scenario: resolve returns postgres backend_type

- **WHEN** `resolve(persona, harness_name)` is called on a persona with
  `database_url` configured
- **THEN** it MUST return a `MemoryConfig` with `backend_type="postgres"`

#### Scenario: export_memory_context delegates to MemoryManager

- **WHEN** `export_memory_context(persona)` is called
- **THEN** it MUST return the output of
  `MemoryManager.export_memory(persona)`

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

### Requirement: Embeddings Consumer Binding for Graphiti

The system SHALL wire a persona's explicit `models:` `bindings:`
entry for the `embeddings` consumer into the Graphiti client factory:
when the binding is declared, `create_graphiti_client(persona)` MUST
resolve `ModelRequest(consumer="embeddings")` through the registry
provider (health-aware) and construct the `Graphiti` client with an
embedder adapter over the raw OpenAI-compatible client binding — the
first chain member with dialect `openai-compatible` and a non-empty
endpoint supplies the wire endpoint and model id; credentials resolve
through the persona-scoped `CredentialProvider` and every embedding
dispatch is gated by the persona's `GuardrailProvider` `model_call`
hook. The reserved `default` binding key MUST NOT activate this
wiring — only an explicit `embeddings` binding does. When no
`embeddings` binding is declared, the factory MUST construct the
client exactly as before (graphiti-core default embedder). When the
binding is declared but cannot be honored (resolution failure, no
`openai-compatible` chain member with an endpoint), the factory MUST
return `None` with a `logging.WARNING`-level message naming the
persona — disabling Graphiti (Postgres-only degradation) rather than
silently embedding through the default cloud path.

#### Scenario: Declared embeddings binding selects the local embedder

- **WHEN** the persona's registry binds `embeddings` to an
  `openai-compatible` entry with endpoint
  `"http://gx10.local:8001/v1"`
- **AND** `create_graphiti_client(persona)` is called
- **THEN** the `Graphiti` client MUST be constructed with an
  `embedder` whose embedding calls POST to
  `http://gx10.local:8001/v1/embeddings` with the entry's wire
  `model_id`

#### Scenario: No embeddings binding preserves current behavior

- **WHEN** the persona declares a `models:` registry without an
  `embeddings` binding (or no registry at all)
- **AND** `create_graphiti_client(persona)` is called
- **THEN** the `Graphiti` client MUST be constructed without an
  `embedder` argument

#### Scenario: Unhonorable binding disables Graphiti instead of cloud fallback

- **WHEN** the persona binds `embeddings` to an entry that is not
  `openai-compatible` or has no endpoint
- **AND** `create_graphiti_client(persona)` is called
- **THEN** the factory MUST return `None`
- **AND** a `logging.WARNING`-level message naming the persona MUST
  be emitted

#### Scenario: Embedding dispatch is budget-gated

- **WHEN** the persona's guardrails deny `model_call` for the bound
  embeddings entry
- **AND** the embedder adapter's `create` is awaited
- **THEN** no HTTP request may be issued and the guardrail denial
  MUST propagate

