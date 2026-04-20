# memory-policy Specification Delta — memory-architecture

## ADDED Requirements

### Requirement: Database Engine Factory

The system SHALL provide a `create_async_engine(persona)` function in
`core/db.py` that returns a cached `AsyncEngine` per persona's
`database_url`. Engines MUST be lazily initialized on first access and
cached by URL.

#### Scenario: Engine created for persona with database_url

- **WHEN** `create_async_engine(persona)` is called with a persona whose
  `database_url` is `"postgresql+asyncpg://localhost/personal"`
- **THEN** it MUST return an `AsyncEngine` instance
- **AND** a subsequent call with the same persona MUST return the same
  engine instance

#### Scenario: Engine not created when database_url is empty

- **WHEN** `create_async_engine(persona)` is called with a persona whose
  `database_url` is `""`
- **THEN** it MUST raise `ValueError` with a message indicating no
  database URL configured

### Requirement: Graphiti Client Factory

The system SHALL provide a `create_graphiti_client(persona)` function in
`core/graphiti.py` that returns a cached `Graphiti` client per persona's
`graphiti_url`. Clients MUST be lazily initialized and cached by URL.

#### Scenario: Client created for persona with graphiti_url

- **WHEN** `create_graphiti_client(persona)` is called with a persona
  whose `graphiti_url` is `"bolt://localhost:7687"`
- **THEN** it MUST return a `Graphiti` client instance

#### Scenario: Client returns None when graphiti_url is empty

- **WHEN** `create_graphiti_client(persona)` is called with a persona
  whose `graphiti_url` is `""`
- **THEN** it MUST return `None`

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

#### Scenario: Preference stores categorized preferences

- **WHEN** a `Preference` is created with `persona="personal"`,
  `category="communication"`, `key="tone"`, `value="concise"`,
  `confidence=0.8`
- **THEN** the record MUST be queryable by persona + category

#### Scenario: Interaction stores session history

- **WHEN** an `Interaction` is created with `persona="personal"`,
  `role="researcher"`, `summary="Found 3 relevant papers"`
- **THEN** `created_at` MUST be automatically set
- **AND** records MUST be queryable by persona with time-range filtering

### Requirement: MemoryManager Class

The system SHALL provide a `MemoryManager` class in `core/memory.py`
that coordinates reads and writes across Postgres and Graphiti backends.
It MUST accept an `AsyncSession` factory and an optional `Graphiti`
client.

#### Scenario: get_context merges Postgres and Graphiti

- **WHEN** `get_context(persona, role)` is called
- **THEN** it MUST return a string containing operational state from
  Postgres
- **AND** it MUST include semantic context from Graphiti if available

#### Scenario: get_context returns Postgres-only when Graphiti unavailable

- **WHEN** `get_context(persona, role)` is called and Graphiti client
  is `None`
- **THEN** it MUST return context from Postgres only without raising

#### Scenario: store_fact persists to Postgres

- **WHEN** `store_fact(persona, "active_project", {"name": "newsletter"})`
  is called
- **THEN** the `memory` table MUST contain a row with that key and value
- **AND** if the key already exists, the value MUST be updated (upsert)

#### Scenario: store_interaction persists to Postgres

- **WHEN** `store_interaction(persona, "researcher", "Found papers")`
  is called
- **THEN** the `interactions` table MUST contain a new row with that
  role and summary

#### Scenario: store_episode ingests into Graphiti

- **WHEN** `store_episode(persona, "User prefers concise replies", "conversation")`
  is called and Graphiti is available
- **THEN** the episode MUST be added via `graphiti_client.add_episode()`

#### Scenario: store_episode is no-op when Graphiti unavailable

- **WHEN** `store_episode()` is called and Graphiti client is `None`
- **THEN** the call MUST log a warning and return without raising

#### Scenario: search queries Graphiti

- **WHEN** `search(persona, "newsletter preferences")` is called
- **THEN** it MUST return results from `graphiti_client.search()`

#### Scenario: export_memory produces structured Markdown

- **WHEN** `export_memory(persona)` is called
- **THEN** the output MUST contain sections for Active Context,
  Preferences, and Recent Interactions
- **AND** if Graphiti is available, it MUST include a Knowledge Graph
  Summary section

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

### Requirement: CLI Database Commands

The system SHALL add CLI subcommands for database operations:
`assistant db upgrade` to run Alembic migrations and
`assistant export-memory -p <persona>` to generate memory.md content.

#### Scenario: db upgrade runs migrations

- **WHEN** `assistant db upgrade` is invoked
- **THEN** Alembic MUST run all pending migrations to head

#### Scenario: export-memory generates memory content

- **WHEN** `assistant export-memory -p personal` is invoked
- **THEN** it MUST output structured Markdown to stdout

#### Scenario: export-memory requires persona flag

- **WHEN** `assistant export-memory` is invoked without `-p`
- **THEN** it MUST exit with an error indicating persona is required

## MODIFIED Requirements

### Requirement: FileMemoryPolicy Stub

The system SHALL retain `FileMemoryPolicy` as a fallback for personas
without `database_url` configured. The `CapabilityResolver` MUST select
`PostgresGraphitiMemoryPolicy` when `database_url` is present and
`FileMemoryPolicy` otherwise.

#### Scenario: FileMemoryPolicy used when no database_url

- **WHEN** a persona has `database_url=""` (empty string)
- **THEN** the `CapabilityResolver` MUST use `FileMemoryPolicy`

#### Scenario: PostgresGraphitiMemoryPolicy used when database_url present

- **WHEN** a persona has `database_url="postgresql+asyncpg://localhost/personal"`
- **THEN** the `CapabilityResolver` MUST use `PostgresGraphitiMemoryPolicy`
