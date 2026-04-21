# Proposal: memory-architecture

## Change ID
`memory-architecture`

## Phase
P2

## Why

The assistant currently loads memory from flat `memory.md` files via
`FileMemoryPolicy`. This is a read-only snapshot with no ability to
persist learned context, track interactions, or build semantic
relationships across sessions. The perplexity review (§1.2) identified
this as "split-brained" — three memory surfaces exist conceptually
(Graphiti, Postgres, memory.md) but only the file surface is wired.

Without a real memory layer, downstream phases cannot function:
- **P7 scheduler** needs stored preferences for morning briefings
- **P8 obsidian-vault** needs a memory backend to index against
- **P12 delegation-context** needs memory snippets for context passing

## What Changes

1. **`src/assistant/core/db.py`** — Async SQLAlchemy engine factory with
   per-persona connection pooling. ParadeDB Postgres target. Alembic
   migration support for schema evolution. Includes `async_session_factory`
   helper and `_clear_engine_cache()` for test isolation.

2. **`src/assistant/core/graphiti.py`** — Graphiti client factory wrapping
   `graphiti_core.Graphiti` with `FalkorDriver` backend (Redis-compatible
   graph DB, already deployed for the newsletter-aggregator system).
   Per-persona FalkorDB connections. FalkorDB host/port/password read from
   persona config env vars. Episode ingestion and semantic search.

3. **`src/assistant/core/memory.py`** — `MemoryManager` class providing:
   - `get_context(persona, role, limit=50)` — unified read from Postgres +
     Graphiti with explicit row caps
   - `store_fact(persona, key, value)` — operational state in Postgres (upsert)
   - `store_interaction(persona, role, summary, metadata=None)` — session
     log in Postgres
   - `store_episode(persona, content, source)` — semantic content in Graphiti
   - `search(persona, query, num_results=5)` — semantic search via Graphiti
   - `export_memory(persona)` → str — generate memory.md content

4. **`PostgresGraphitiMemoryPolicy`** — New `MemoryPolicy` implementation.
   `CapabilityResolver` selects it when `persona.database_url` is
   non-empty; falls back to `FileMemoryPolicy` otherwise.

5. **Database schema** (Alembic-managed, ParadeDB Postgres):
   - `memory` — key-value operational state; UNIQUE(persona, key)
   - `preferences` — learned user preferences with confidence;
     UNIQUE(persona, category, key)
   - `interactions` — session history with role, summary, timestamps

6. **CLI subcommands**:
   - `assistant db upgrade` — run Alembic migrations to head
   - `assistant db downgrade <revision>` — rollback to revision
   - `assistant export-memory -p <persona>` — generate memory.md to stdout

7. **Dependency additions** — `graphiti-core`, `alembic`, `falkordb` in
   `pyproject.toml`.

## What Doesn't Change

- `FileMemoryPolicy` remains available for personas without database config
- `HostProvidedMemoryPolicy` unchanged (Claude Code/Codex manage their own)
- `MemoryPolicy` protocol signature unchanged — P2 adds a new implementation
- `PersonaConfig` dataclass unchanged — FalkorDB config read from
  `persona.raw["graphiti"]` at factory level
- Existing tests continue to pass against file-based fixtures

## Impact

Specs modified by this change:
- **memory-policy** — adds 6 new requirements (engine factory, Graphiti
  factory, schema, MemoryManager, PostgresGraphitiMemoryPolicy,
  Alembic infrastructure), modifies FileMemoryPolicy stub requirement
- **cli-interface** — adds CLI db command group and export-memory command
- **capability-resolver** — modifies SDK harness memory selection logic

## Approaches Considered

### Approach A: Layered Manager with Dual Backends (Recommended)

`MemoryManager` owns both a SQLAlchemy async session and a Graphiti
client. It routes writes to the appropriate backend based on content
type: operational facts → Postgres, semantic episodes → Graphiti.
`get_context()` merges both sources with explicit row limits.
`PostgresGraphitiMemoryPolicy` delegates to `MemoryManager` internally.

**Pros:**
- Clean separation: consumers call `MemoryManager`, never touch raw
  clients directly
- Matches the three-tier hierarchy from perplexity §1.2 exactly
- `export_memory()` has access to both backends for complete snapshots
- Graceful degradation: if FalkorDB is unavailable, Postgres still works

**Cons:**
- Two infrastructure dependencies (Postgres + FalkorDB) for full function
- MemoryManager becomes a coordination point — must handle partial failures

**Effort:** L

### Approach B: Postgres-First with Graphiti Facade

All memory goes through Postgres (operational + embeddings via pgvector).
Graphiti client is wrapped behind a thin facade that's called only for
entity extraction and relationship building, not as a primary store.

**Pros:** Single primary datastore simplifies operations
**Cons:** Loses Graphiti's temporal knowledge graph strengths
**Effort:** M

### Approach C: Event-Sourced Memory Log

All memory writes append to an immutable event log. Materialized views
derive current state. Graphiti subscribes to the event stream.

**Pros:** Complete audit trail, replayable
**Cons:** Significant complexity overkill for single-user personas
**Effort:** XL

### Selected Approach

**Approach A: Layered Manager with Dual Backends** — directly implements
the three-tier hierarchy from perplexity §1.2, maintains clean
separation of concerns, and provides graceful degradation. FalkorDB
(already deployed for the newsletter-aggregator) is the Graphiti backend.

## Dependencies

- **Requires**: P1.8 `capability-protocols` (archived) — MemoryPolicy protocol
- **Unblocks**: P7 `scheduler`, P8 `obsidian-vault`, P12 `delegation-context`

## Risks

1. **FalkorDB availability** — Graphiti requires FalkorDB. Mitigated by
   graceful degradation: `MemoryManager` operates in Postgres-only mode
   if `graphiti_url` is empty or FalkorDB is unreachable.
2. **Schema evolution** — Alembic migrations must work with ParadeDB.
   Mitigated by testing against standard Postgres in CI (ParadeDB is a
   superset).
3. **Test isolation** — Tests must not require running Postgres/FalkorDB.
   Mitigated by `FileMemoryPolicy` as test default + mock-based unit
   tests for MemoryManager + `@pytest.mark.integration` for infra tests.
4. **Credential management** — Database and FalkorDB passwords resolved
   via persona env vars (`_env()` pattern). No credentials in YAML files
   or code. The existing `*_env` suffix convention in persona.yaml is
   extended with FalkorDB-specific fields.
