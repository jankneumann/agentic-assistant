# Tasks — memory-architecture

Tasks are ordered TDD-style within each phase: test tasks first,
implementation tasks depend on their corresponding tests. Phases are
ordered so each builds on a compileable/importable tree from the prior
phase.

## Phase 1 — Dependencies, ORM Models, and Test Infrastructure

- [x] 1.1 Add `graphiti-core`, `alembic`, and `falkordb` to
  `pyproject.toml` dependencies. Run `uv sync` to verify resolution
  alongside existing pins (`sqlalchemy>=2.0`, `asyncpg>=0.29`,
  `langchain>=0.3`). Record exact resolved versions.
  **Dependencies**: none

- [x] 1.2 Create shared test fixtures in `tests/conftest.py`:
  - `mock_async_session` — `AsyncMock` session with query/execute
  - `mock_graphiti_client` — `AsyncMock` Graphiti with search/add_episode
  - `mock_session_factory` — returns `mock_async_session`
  - `autouse` fixture calling `_clear_engine_cache()` and
    `_clear_graphiti_cache()` before each test
  **Design decisions**: D9 (shared mock fixtures)
  **Dependencies**: 1.1

- [x] 1.3 Write `tests/test_db.py` encoding:
  - Engine created for persona with database_url (returns AsyncEngine)
  - Engine dialect uses asyncpg driver
  - Engine cached on second call (same instance returned)
  - Engine raises ValueError when database_url is empty
  - Session factory returns async_sessionmaker
  - Cache cleared between tests via `_clear_engine_cache()`
  **Spec scenarios**: Database Engine Factory (3 scenarios),
  Async Session Factory (1 scenario)
  **Design decisions**: D2 (lazy init, cached by URL)
  **Dependencies**: 1.2

- [x] 1.4 Implement `src/assistant/core/db.py`:
  - `Base = DeclarativeBase()` for ORM models
  - `create_async_engine(persona)` with per-URL caching, pool_size=2,
    max_overflow=0
  - `async_session_factory(engine)` returning `async_sessionmaker`
  - `_clear_engine_cache()` for test isolation
  **Design decisions**: D2 (lazy init), D6 (ORM models)
  **Dependencies**: 1.3

- [x] 1.5 Write `tests/test_memory_models.py` encoding:
  - MemoryEntry stores persona + key + JSONB value + updated_at (auto-set)
  - MemoryEntry UNIQUE(persona, key) constraint raises on duplicate
  - Preference stores persona + category + key + value + confidence +
    updated_at (auto-set on create and update)
  - Preference UNIQUE(persona, category, key) constraint raises on duplicate
  - Interaction stores persona + role + summary + metadata (JSONB,
    defaults to {}) + created_at (auto-set)
  - All models inherit from shared Base
  **Spec scenarios**: Memory Database Schema (3 scenarios)
  **Design decisions**: D4 (three tables with constraints), D6 (ORM)
  **Dependencies**: 1.4

- [x] 1.6 Implement ORM models in `src/assistant/core/models.py`:
  - `MemoryEntry(Base)` with columns and UNIQUE(persona, key)
  - `Preference(Base)` with columns and UNIQUE(persona, category, key)
  - `Interaction(Base)` with columns, metadata defaults to {},
    INDEX(persona, created_at DESC)
  - All timestamp columns use `server_default=func.now()`, updated_at
    also uses `onupdate=func.now()`
  **Design decisions**: D4, D6
  **Dependencies**: 1.5

## Phase 2 — Alembic Migrations

- [x] 2.1 Initialize Alembic in `src/assistant/migrations/`:
  - `alembic.ini` co-located with migrations (programmatic access only)
  - `env.py` importing engine factory from `core/db.py`, using
    `run_async()` for async engine support
  - Document that CLI constructs Config via absolute path:
    `Path(__file__).resolve().parent.parent / "migrations" / "alembic.ini"`
  **Spec scenarios**: Alembic Migration Infrastructure (setup)
  **Design decisions**: D3 (migrations co-located, programmatic access)
  **Dependencies**: 1.6

- [x] 2.2 Create initial migration
  `src/assistant/migrations/versions/001_initial_memory_schema.py`:
  - Creates `memory`, `preferences`, `interactions` tables matching
    `contracts/db/schema.sql`
  - Uses `sqlalchemy.text()` for any raw SQL per §7.2 guidance
  - Downgrade drops all three tables
  **Spec scenarios**: Alembic Migration Infrastructure (2 scenarios:
  initial creates tables, downgrade reverses)
  **Design decisions**: D3, D4, D6
  **Dependencies**: 2.1

## Phase 3 — Graphiti Client Factory (parallel with Phase 1.3-2.2)

- [x] 3.1 Write `tests/test_graphiti_factory.py` encoding:
  - Client created for persona with graphiti_url + FalkorDB env vars
  - Client uses FalkorDriver
  - Client cached on second call (same instance)
  - Returns None when graphiti_url is empty
  - Cache cleared between tests via `_clear_graphiti_cache()`
  **Spec scenarios**: Graphiti Client Factory (3 scenarios)
  **Design decisions**: D2 (lazy init, cached), D10 (credentials via env),
  D11 (FalkorDriver config)
  **Dependencies**: 1.1

- [x] 3.2 Implement `src/assistant/core/graphiti.py`:
  - `create_graphiti_client(persona)` → `Graphiti | None`
  - Per-persona caching in module-level dict
  - Reads FalkorDB config from `persona.raw["graphiti"]`:
    `host_env`, `port_env`, `password_env`, `database`
  - Resolves env vars via `_env()` from `persona.py`
  - Creates `FalkorDriver(host, port, username="", password, database)`
  - `_clear_graphiti_cache()` for test isolation
  **Design decisions**: D2, D10, D11
  **Dependencies**: 3.1

## Phase 4 — MemoryManager

- [x] 4.1 Write `tests/test_memory_manager.py` encoding Postgres-path
  scenarios:
  - get_context returns string with `## Active Context` section
  - get_context limits Postgres reads to `limit` (default 50)
  - get_context returns Postgres-only when Graphiti is None
  - store_fact persists to Postgres (upsert, refreshes updated_at)
  - store_fact rejects non-JSON-serializable values with ValueError
  - store_interaction persists with role, summary, metadata
  - store_interaction defaults metadata to {}
  - export_memory produces Markdown with Active Context, Preferences,
    Recent Interactions sections
  - export_memory limits interactions to 100
  **Spec scenarios**: MemoryManager (get_context ×3, store_fact ×2,
  store_interaction ×2, export_memory ×1 partial)
  **Design decisions**: D1, D5, D7
  **Dependencies**: 1.6, 1.2

- [x] 4.2 Write `tests/test_memory_manager_graphiti.py` encoding
  Graphiti-path scenarios:
  - get_context includes `## Semantic Context` when Graphiti available
  - get_context degrades on Graphiti connection error (WARNING log)
  - store_episode calls graphiti_client.add_episode()
  - store_episode is no-op when Graphiti is None (WARNING log with
    persona name and source)
  - store_episode degrades on Graphiti connection error
  - search returns list[str] of episode content from Graphiti
  - search defaults to num_results=5
  - search returns empty list when Graphiti is None
  - export_memory includes Knowledge Graph Summary when Graphiti available
  - export_memory omits Knowledge Graph Summary when Graphiti is None
  **Spec scenarios**: MemoryManager (get_context degradation,
  store_episode ×3, search ×2, export_memory ×2)
  **Dependencies**: 1.6, 1.2

- [x] 4.3 Implement `src/assistant/core/memory.py` — `MemoryManager`
  Postgres path:
  - `__init__(session_factory, graphiti_client=None)`
  - `async get_context(persona, role, limit=50) → str` — queries
    memory table, formats as Markdown with `## Active Context`
  - `async store_fact(persona, key, value) → None` — upsert with
    JSON-serializability check
  - `async store_interaction(persona, role, summary, metadata=None)`
  - `async export_memory(persona) → str` — Postgres sections
  **Design decisions**: D1, D7
  **Dependencies**: 4.1

- [x] 4.4 Implement `src/assistant/core/memory.py` — `MemoryManager`
  Graphiti path:
  - Extend `get_context` with `## Semantic Context` section from Graphiti
  - Graceful degradation on connection error (WARNING log)
  - `async store_episode(persona, content, source) → None`
  - `async search(persona, query, num_results=5) → list[str]`
  - Extend `export_memory` with `## Knowledge Graph Summary` section
  **Design decisions**: D1, D5, D7, D11
  **Dependencies**: 4.2, 4.3

## Phase 5 — PostgresGraphitiMemoryPolicy and Resolver

- [x] 5.1 Write `tests/test_postgres_memory_policy.py` encoding:
  - Satisfies MemoryPolicy protocol (isinstance check)
  - resolve returns MemoryConfig with backend_type="postgres"
  - export_memory_context delegates to MemoryManager.export_memory
  **Spec scenarios**: PostgresGraphitiMemoryPolicy (3 scenarios)
  **Design decisions**: D1
  **Dependencies**: 4.4

- [x] 5.2 Implement `PostgresGraphitiMemoryPolicy` in
  `src/assistant/core/capabilities/memory.py`:
  - Instantiates `MemoryManager` with session factory + Graphiti client
  - `resolve()` returns `MemoryConfig(backend_type="postgres", ...)`
  - `export_memory_context()` calls `MemoryManager.export_memory()`
  **Dependencies**: 5.1

- [x] 5.3 Write `tests/test_resolver_memory_selection.py` encoding:
  - Resolver selects PostgresGraphitiMemoryPolicy when persona has
    database_url
  - Resolver selects FileMemoryPolicy when persona has empty database_url
  - Host harness memory unchanged (HostProvidedMemoryPolicy)
  **Spec scenarios**: capability-resolver delta (3 scenarios)
  **Dependencies**: 5.2

- [x] 5.4 Update `src/assistant/core/capabilities/resolver.py`:
  - Default memory selection in `resolve()` checks `persona.database_url`
  - Non-empty → `PostgresGraphitiMemoryPolicy`
  - Empty → `FileMemoryPolicy`
  - Host harness path unchanged (`HostProvidedMemoryPolicy`)
  **Dependencies**: 5.3

## Phase 6 — CLI Commands (parallel with Phase 5)

- [x] 6.1 Write `tests/test_cli_db.py` encoding:
  - `assistant db upgrade` invokes Alembic upgrade to head
  - `assistant db upgrade` exits non-zero when database unreachable
  - `assistant db downgrade <revision>` invokes Alembic downgrade
  - `assistant export-memory -p personal` produces structured Markdown
  - `assistant export-memory` without `-p` exits with error
  - `assistant export-memory -p personal` exits non-zero when persona
    has no database_url
  **Spec scenarios**: cli-interface delta (all 6 scenarios)
  **Design decisions**: D8
  **Dependencies**: 4.3, 2.2

- [x] 6.2 Add CLI subcommands to `src/assistant/cli.py`:
  - `db` group with `upgrade` and `downgrade` subcommands
  - `export-memory` command with `-p/--persona` required option
  - `db upgrade` runs `alembic.command.upgrade(config, "head")` with
    Config constructed via absolute path
  - `db downgrade` runs `alembic.command.downgrade(config, revision)`
  - `export-memory` loads persona, creates MemoryManager, calls
    `export_memory()`, prints to stdout; exits non-zero if no database_url
  **Design decisions**: D3 (absolute Config path), D8
  **Dependencies**: 6.1

## Phase 7 — Integration and Validation

- [x] 7.1 Update existing `tests/test_capabilities.py` and
  `tests/test_memory_policy.py` to verify `FileMemoryPolicy` still
  works unchanged. Update `tests/test_capability_resolver.py` to cover
  both branches: mock persona with `database_url=""` (expects
  FileMemoryPolicy) and with `database_url="postgresql://..."` (expects
  PostgresGraphitiMemoryPolicy). All existing scenarios MUST continue
  to pass.
  **Dependencies**: 5.4, 6.2

- [x] 7.2 Run `uv run ruff check .` — zero errors.
  **Dependencies**: 7.1

- [x] 7.3 Run `uv run pytest tests/` — all tests pass (excluding
  `@pytest.mark.integration` tests).
  **Dependencies**: 7.1 (parallel with 7.2)

- [x] 7.4 `openspec validate memory-architecture --strict` passes.
  **Dependencies**: 7.2, 7.3
