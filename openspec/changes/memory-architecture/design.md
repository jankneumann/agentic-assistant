# Design: memory-architecture

## Selected Approach

Approach A — Layered Manager with Dual Backends.

## Architecture

```
                    ┌─────────────────────────┐
                    │   MemoryManager          │
                    │  get_context()           │
                    │  store_fact()            │
                    │  store_interaction()     │
                    │  store_episode()         │
                    │  search()               │
                    │  export_memory()         │
                    └────────┬────────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
      ┌─────────▼──────────┐   ┌──────────▼─────────┐
      │   Postgres Layer   │   │   Graphiti Layer    │
      │  (operational)     │   │   (semantic)        │
      │                    │   │                     │
      │  memory table      │   │  episodes           │
      │  preferences table │   │  entities / edges   │
      │  interactions table│   │  temporal facts      │
      │                    │   │                     │
      │  AsyncEngine       │   │  Graphiti client     │
      │  (asyncpg)         │   │  (FalkorDB driver)  │
      └────────────────────┘   └─────────────────────┘
```

## Design Decisions

### D1: MemoryManager is a plain class, not a Protocol

`MemoryPolicy` is the Protocol that harnesses consume — it has two
methods (`resolve`, `export_memory_context`). `MemoryManager` is the
internal implementation that `PostgresGraphitiMemoryPolicy` delegates
to. Consumers never import `MemoryManager` directly — they receive a
`MemoryPolicy` through the `CapabilityResolver`.

The two method names are distinct by design:
- `MemoryManager.export_memory()` — the implementation that queries both backends
- `MemoryPolicy.export_memory_context()` — the protocol-level wrapper that delegates to it

### D2: Per-persona engine factory with lazy initialization

`create_async_engine(persona)` returns a cached `AsyncEngine` per
`persona.database_url`. Engines are created on first access and cached
in a module-level dict keyed by URL. Same pattern for Graphiti clients.

Both caches export `_clear_engine_cache()` / `_clear_graphiti_cache()`
functions for test isolation. An `autouse` fixture in `conftest.py`
clears both caches before each test.

Pool defaults: `pool_size=2, max_overflow=0` — appropriate for a
single-user assistant. Configurable via persona harness config if
needed in future phases.

### D3: Alembic migrations in `src/assistant/migrations/`

```
src/assistant/migrations/
  alembic.ini
  env.py         # async engine from core/db.py
  versions/
    001_initial_memory_schema.py
```

`alembic.ini` is intentionally co-located with migrations because all
Alembic access is programmatic via `alembic.command.upgrade(config, "head")`
— never via the `alembic` CLI directly. The CLI constructs the `Config`
object using an absolute path:
`Path(__file__).resolve().parent.parent / "migrations" / "alembic.ini"`.

### D4: Three tables with explicit constraints

| Table | Purpose | Key columns | Constraints |
|-------|---------|-------------|-------------|
| `memory` | Key-value operational state | `persona`, `key`, `value` (JSONB), `updated_at` | UNIQUE(persona, key) |
| `preferences` | Learned user preferences | `persona`, `category`, `key`, `value` (JSONB), `confidence`, `updated_at` | UNIQUE(persona, category, key) |
| `interactions` | Session history | `persona`, `role`, `summary`, `metadata` (JSONB), `created_at` | INDEX(persona, created_at DESC) |

Separate tables for distinct access patterns. `memory` is read-heavy at
session start. `preferences` are queried by category. `interactions`
are append-only with time-range queries.

### D5: Graceful degradation when FalkorDB is unavailable

`MemoryManager.__init__` accepts optional `graphiti_client`. Degradation
covers two cases:

1. **Client is None** (empty `graphiti_url`): all Graphiti methods return
   empty results silently.
2. **Client raises connection error** (FalkorDB unreachable): Graphiti
   methods catch connection errors, emit a `logging.WARNING`-level
   message including the persona name, and return empty results. The
   call never raises to the caller.

`get_context()` returns Postgres-only context in both cases.
`export_memory()` omits the Knowledge Graph Summary section.

### D6: SQLAlchemy ORM models with text() for raw SQL

Tables are defined as SQLAlchemy `DeclarativeBase` models. All queries
use the ORM. Raw SQL in Alembic migrations is wrapped with
`sqlalchemy.text()` per §7.2 guidance.

### D7: Structured Markdown output formats

**`export_memory(persona)`** produces:
```markdown
# Memory — {persona.display_name}

## Active Context
{key-value pairs from memory table, limited to 50 most recent}

## Preferences
{categorized preferences, ordered by confidence DESC}

## Recent Interactions
{last 100 interactions with role and timestamp}

## Knowledge Graph Summary
{top entities and relationships from Graphiti}
{included only when Graphiti client is available and responsive}
```

**`get_context(persona, role, limit=50)`** produces:
```markdown
## Active Context
{up to `limit` most-recently-updated memory entries}

## Semantic Context
{Graphiti search results relevant to role, if available}
```

Both methods return UTF-8 Markdown strings ending with a single
trailing newline.

### D8: CLI subcommands

- `assistant db upgrade` — run Alembic migrations to head
- `assistant db downgrade <revision>` — rollback to specified revision
- `assistant export-memory -p <persona>` — generate memory.md to stdout

`db upgrade/downgrade` exit non-zero with an error message if the
database is unreachable. `export-memory` exits non-zero if the persona
has no `database_url` configured.

### D9: Test strategy

**Unit tests** mock `AsyncSession` and `Graphiti` client. Shared
fixtures in `tests/conftest.py`:
- `mock_async_session` — `AsyncMock` session with query/execute
- `mock_graphiti_client` — `AsyncMock` Graphiti with search/add_episode
- `mock_session_factory` — returns `mock_async_session`
- `autouse` cache-clearing fixture for `_clear_engine_cache()` and
  `_clear_graphiti_cache()`

**Integration tests** (marked `@pytest.mark.integration`) require
running Postgres and FalkorDB. Skipped in CI unless services are
available.

### D10: Credential management

All database and FalkorDB credentials are resolved from environment
variables via the existing `_env()` pattern in `persona.py`. No
credentials are stored in YAML files or code.

Persona config pattern:
```yaml
database:
  url_env: PERSONAL_DATABASE_URL    # postgresql+asyncpg://user:pass@host/db

graphiti:
  url_env: PERSONAL_GRAPHITI_URL    # activation signal (non-empty = enabled)
  host_env: PERSONAL_FALKORDB_HOST
  port_env: PERSONAL_FALKORDB_PORT
  password_env: PERSONAL_FALKORDB_PASSWORD
  database: personal_graph
```

The `create_graphiti_client` factory reads FalkorDB-specific fields
from `persona.raw["graphiti"]`, resolving `*_env` fields via `_env()`.
`PersonaConfig.graphiti_url` remains the activation signal — if empty,
Graphiti is disabled for the persona.

### D11: FalkorDB driver configuration

Graphiti client is created with `graphiti_core`'s `FalkorDriver`:
```python
from graphiti_core.driver.falkordb_driver import FalkorDriver

driver = FalkorDriver(
    host=host,       # from persona graphiti.host_env
    port=port,       # from persona graphiti.port_env (default 6379)
    username="",     # FalkorDB typically uses password-only auth
    password=password,  # from persona graphiti.password_env
    database=database,  # from persona graphiti.database (default: {name}_graph)
)
client = Graphiti(driver=driver)
```

This matches the proven pattern in `agentic-newsletter-aggregator`'s
`FalkorDBGraphDBProvider`.
