# Tasks — memory-architecture

Tasks are ordered TDD-style within each phase: test tasks first,
implementation tasks depend on their corresponding tests. Phases are
ordered so each builds on a compileable/importable tree from the prior
phase.

## Phase 1 — Dependencies and ORM Models

- [ ] 1.1 Add `graphiti-core`, `alembic`, and `neo4j` to `pyproject.toml`
  dependencies. Run `uv sync` to verify resolution.
  **Dependencies**: none

- [ ] 1.2 Write `tests/test_db.py` encoding:
  - Engine created for persona with database_url
  - Engine cached on second call (same instance)
  - Engine raises ValueError when database_url is empty
  - Engine uses asyncpg driver
  **Spec scenarios**: Database Engine Factory (all 2 scenarios)
  **Design decisions**: D2 (lazy init, cached by URL)
  **Dependencies**: 1.1

- [ ] 1.3 Implement `src/assistant/core/db.py`:
  - `Base = declarative_base()` for ORM models
  - `create_async_engine(persona)` with per-URL caching
  - `async_session_factory(engine)` returning `async_sessionmaker`
  **Design decisions**: D2 (lazy init), D6 (ORM models)
  **Dependencies**: 1.2

- [ ] 1.4 Write `tests/test_memory_models.py` encoding:
  - MemoryEntry stores persona + key + JSONB value + updated_at
  - Preference stores persona + category + key + value + confidence
  - Interaction stores persona + role + summary + metadata + created_at
  - All models inherit from shared Base
  **Spec scenarios**: Memory Database Schema (all 3 scenarios)
  **Design decisions**: D4 (three tables), D6 (ORM models)
  **Dependencies**: 1.3

- [ ] 1.5 Implement ORM models in `src/assistant/core/models.py`:
  - `MemoryEntry(Base)` with `persona`, `key`, `value` (JSONB),
    `updated_at` (auto-set)
  - `Preference(Base)` with `persona`, `category`, `key`, `value`
    (JSONB), `confidence` (Float), `updated_at`
  - `Interaction(Base)` with `persona`, `role`, `summary`,
    `metadata` (JSONB), `created_at` (auto-set)
  - Unique constraint on `(persona, key)` for MemoryEntry
  - Index on `(persona, category)` for Preference
  - Index on `(persona, created_at)` for Interaction
  **Design decisions**: D4, D6
  **Dependencies**: 1.4

## Phase 2 — Alembic Migrations

- [ ] 2.1 Initialize Alembic in `src/assistant/migrations/`:
  - `alembic.ini` with async driver config
  - `env.py` importing engine factory from `core/db.py`
  - Configure `run_async()` for async engine support
  **Design decisions**: D3 (migrations in src/assistant/migrations/)
  **Dependencies**: 1.5

- [ ] 2.2 Create initial migration
  `src/assistant/migrations/versions/001_initial_memory_schema.py`:
  - Creates `memory`, `preferences`, `interactions` tables
  - Uses `sqlalchemy.text()` for any raw SQL per §7.2 guidance
  - Includes downgrade (drop tables)
  **Design decisions**: D3, D4, D6
  **Dependencies**: 2.1

## Phase 3 — Graphiti Client Factory

- [ ] 3.1 Write `tests/test_graphiti_factory.py` encoding:
  - Client created for persona with graphiti_url
  - Client cached on second call
  - Returns None when graphiti_url is empty
  **Spec scenarios**: Graphiti Client Factory (all 2 scenarios)
  **Design decisions**: D2 (lazy init, cached by URL)
  **Dependencies**: 1.1

- [ ] 3.2 Implement `src/assistant/core/graphiti.py`:
  - `create_graphiti_client(persona)` → `Graphiti | None`
  - Per-URL caching in module-level dict
  - Parses `graphiti_url` for Neo4j URI, reads Neo4j credentials
    from persona env vars
  **Design decisions**: D2
  **Dependencies**: 3.1

## Phase 4 — MemoryManager

- [ ] 4.1 Write `tests/test_memory_manager.py` encoding:
  - get_context merges Postgres and Graphiti
  - get_context returns Postgres-only when Graphiti unavailable
  - store_fact persists to Postgres (upsert)
  - store_interaction persists to Postgres
  - store_episode ingests into Graphiti
  - store_episode is no-op when Graphiti unavailable
  - search queries Graphiti
  - export_memory produces structured Markdown with all sections
  - export_memory omits Knowledge Graph section when Graphiti unavailable
  **Spec scenarios**: MemoryManager Class (all 8 scenarios)
  **Design decisions**: D1 (plain class), D5 (graceful degradation),
  D7 (structured Markdown)
  **Dependencies**: 1.5, 3.2

- [ ] 4.2 Implement `src/assistant/core/memory.py` — `MemoryManager`:
  - `__init__(session_factory, graphiti_client=None)`
  - `async get_context(persona, role) → str`
  - `async store_fact(persona, key, value) → None`
  - `async store_interaction(persona, role, summary, metadata=None) → None`
  - `async store_episode(persona, content, source) → None`
  - `async search(persona, query, num_results=5) → list[str]`
  - `async export_memory(persona) → str`
  **Design decisions**: D1, D5, D7
  **Dependencies**: 4.1

## Phase 5 — PostgresGraphitiMemoryPolicy

- [ ] 5.1 Write `tests/test_postgres_memory_policy.py` encoding:
  - Satisfies MemoryPolicy protocol (isinstance check)
  - resolve returns MemoryConfig with backend_type="postgres"
  - export_memory_context delegates to MemoryManager.export_memory
  - Falls back to FileMemoryPolicy when database_url is empty
  **Spec scenarios**: PostgresGraphitiMemoryPolicy (all 3 scenarios),
  MODIFIED FileMemoryPolicy (both scenarios)
  **Design decisions**: D1 (delegates to MemoryManager)
  **Dependencies**: 4.2

- [ ] 5.2 Implement `PostgresGraphitiMemoryPolicy` in
  `src/assistant/core/capabilities/memory.py`:
  - Instantiates `MemoryManager` with session factory + Graphiti client
  - `resolve()` returns `MemoryConfig(backend_type="postgres", ...)`
  - `export_memory_context()` calls `MemoryManager.export_memory()`
  **Dependencies**: 5.1

- [ ] 5.3 Update `src/assistant/core/capabilities/resolver.py`:
  - Default memory factory selects `PostgresGraphitiMemoryPolicy` when
    persona has `database_url`, `FileMemoryPolicy` otherwise
  **Dependencies**: 5.2

## Phase 6 — CLI Commands

- [ ] 6.1 Write `tests/test_cli_db.py` encoding:
  - `assistant db upgrade` invokes Alembic upgrade to head
  - `assistant export-memory -p personal` produces structured Markdown
  - `assistant export-memory` without `-p` exits with error
  **Spec scenarios**: CLI Database Commands (all 3 scenarios)
  **Design decisions**: D8 (CLI subcommand groups)
  **Dependencies**: 4.2, 2.2

- [ ] 6.2 Add CLI subcommands to `src/assistant/cli.py`:
  - `db` group with `upgrade` and `downgrade` subcommands
  - `export-memory` command with `-p/--persona` required option
  - `db upgrade` runs `alembic.command.upgrade(config, "head")`
  - `export-memory` loads persona, creates MemoryManager, calls
    `export_memory()`, prints to stdout
  **Design decisions**: D8
  **Dependencies**: 6.1

## Phase 7 — Integration and Validation

- [ ] 7.1 Update existing `tests/test_capabilities.py` and
  `tests/test_memory_policy.py` to verify `FileMemoryPolicy` still
  works unchanged. All existing scenarios MUST continue to pass.
  **Dependencies**: 5.3

- [ ] 7.2 Run `uv run ruff check .` — zero errors.
  **Dependencies**: 7.1

- [ ] 7.3 Run `uv run pytest tests/` — all tests pass (excluding
  `@pytest.mark.integration` tests).
  **Dependencies**: 7.2

- [ ] 7.4 `openspec validate memory-architecture --strict` passes.
  **Dependencies**: 7.3
