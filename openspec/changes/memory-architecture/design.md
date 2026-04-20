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
                    │  export_memory()         ���
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
      │  (asyncpg)         │   │  (neo4j)            │
      └────────────────────┘   └─────────────────────┘
```

## Design Decisions

### D1: MemoryManager is a plain class, not a Protocol

`MemoryPolicy` is the Protocol that harnesses consume — it has two
methods (`resolve`, `export_memory_context`). `MemoryManager` is the
internal implementation that `PostgresGraphitiMemoryPolicy` delegates
to. Consumers never import `MemoryManager` directly — they receive a
`MemoryPolicy` through the `CapabilityResolver`.

**Why**: Keeps the public interface narrow. Harnesses only need to know
about `MemoryPolicy`. The richer `MemoryManager` API (store, search,
export) is used by the CLI and by delegation code that explicitly
needs memory writes.

### D2: Per-persona engine factory with lazy initialization

`create_engine(persona)` returns a cached `AsyncEngine` per
`persona.database_url`. Engines are created on first access and cached
in a module-level dict. Same pattern for Graphiti clients keyed by
`persona.graphiti_url`.

**Why**: Personas are loaded at startup but engines should only connect
when actually needed. Connection pooling is per-persona — one persona's
pool exhaustion doesn't affect another.

### D3: Alembic migrations live in `src/assistant/migrations/`

Standard Alembic layout:
```
src/assistant/migrations/
  alembic.ini
  env.py         # async engine from core/db.py
  versions/
    001_initial_memory_schema.py
```

`env.py` imports the engine factory from `core/db.py` and runs
migrations with `run_async()`. The CLI `assistant db upgrade` subcommand
invokes Alembic programmatically.

**Why**: Keeps migrations co-located with the package. Alembic's async
support works with our existing asyncpg + SQLAlchemy stack. Programmatic
invocation avoids requiring users to know Alembic CLI.

### D4: Three tables, not one

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `memory` | Key-value operational state | `persona`, `key`, `value` (JSONB), `updated_at` |
| `preferences` | Learned user preferences | `persona`, `category`, `key`, `value` (JSONB), `confidence`, `updated_at` |
| `interactions` | Session history | `persona`, `role`, `summary`, `metadata` (JSONB), `created_at` |

**Why**: Distinct access patterns warrant distinct tables. `memory` is
read-heavy at session start. `preferences` are queried by category.
`interactions` are append-only with time-range queries. Separate tables
allow independent indexing and retention policies.

### D5: Graceful degradation when Graphiti is unavailable

`MemoryManager.__init__` accepts optional `graphiti_client`. If `None`
(empty `graphiti_url` in persona config) or if Neo4j is unreachable,
all Graphiti methods return empty results and log warnings instead of
raising. `get_context()` returns Postgres-only context.

**Why**: Not every persona needs semantic memory. The personal persona
may start with just Postgres. Graphiti adds value but shouldn't be a
hard requirement for the system to function.

### D6: SQLAlchemy ORM models, not raw SQL

Tables are defined as SQLAlchemy `DeclarativeBase` models. All queries
use the ORM. Raw SQL is wrapped with `sqlalchemy.text()` per §7.2
guidance when needed (e.g., in Alembic migrations).

**Why**: Type-safe queries, automatic parameter binding (SQL injection
prevention), compatibility with Alembic autogenerate.

### D7: export_memory produces structured Markdown

`MemoryManager.export_memory()` generates a Markdown document with
sections:
```markdown
# Memory — {persona.display_name}
## Active Context
{key-value pairs from memory table}
## Preferences
{categorized preferences}
## Recent Interactions
{last N interactions with role and timestamp}
## Knowledge Graph Summary
{top entities and relationships from Graphiti}
```

**Why**: Human-readable, diff-friendly in git, consumable by host
harnesses (Claude Code, Codex) that read memory.md as context.

### D8: CLI subcommands under `assistant db` group

New CLI command group:
- `assistant db upgrade` — run Alembic migrations to head
- `assistant db downgrade <revision>` — rollback
- `assistant export-memory -p <persona>` — generate memory.md

**Why**: Keeps database operations grouped. `export-memory` is separate
because it's a read-only operation that doesn't modify the schema.

### D9: Test strategy — unit tests with mocks, optional integration markers

Unit tests mock `AsyncSession` and `Graphiti` client. They verify
`MemoryManager` routing logic, `PostgresGraphitiMemoryPolicy` protocol
compliance, and export formatting.

Integration tests (marked `@pytest.mark.integration`) require running
Postgres and Neo4j. They're skipped in CI unless services are available.
The existing `FileMemoryPolicy` tests remain unchanged.

**Why**: Core logic is testable without infrastructure. Integration
tests catch real connection issues but shouldn't block CI.
