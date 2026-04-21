# memory-policy Specification Delta — memory-architecture

## ADDED Requirements

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

## MODIFIED Requirements

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
