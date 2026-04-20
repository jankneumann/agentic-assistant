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
   migration support for schema evolution.

2. **`src/assistant/core/graphiti.py`** — Graphiti client factory wrapping
   `graphiti_core.Graphiti`. Per-persona Neo4j connections. Episode
   ingestion and semantic search.

3. **`src/assistant/core/memory.py`** — `MemoryManager` class providing:
   - `get_context(persona, role)` — unified read from Postgres + Graphiti
   - `store_fact(persona, key, value)` — operational state in Postgres
   - `store_interaction(persona, role, summary)` — session log in Postgres
   - `store_episode(persona, content, source)` — semantic content in Graphiti
   - `search(persona, query)` — semantic search via Graphiti
   - `export_memory(persona)` → str — generate memory.md content

4. **`PostgresGraphitiMemoryPolicy`** — New `MemoryPolicy` implementation
   replacing `FileMemoryPolicy` as the default for SDK harnesses when
   `database_url` is configured.

5. **Database schema** (Alembic-managed):
   - `memory` — key-value operational state (active projects, routing decisions)
   - `preferences` — learned user preferences
   - `interactions` — session history with role, summary, timestamps

6. **CLI `export-memory` subcommand** — Generates `memory.md` from
   Postgres + Graphiti. Invoked explicitly, not via hooks.

7. **Dependency additions** — `graphiti-core`, `alembic`, `neo4j` in
   `pyproject.toml`.

## What Doesn't Change

- `FileMemoryPolicy` remains available for personas without database config
- `HostProvidedMemoryPolicy` unchanged (Claude Code/Codex manage their own memory)
- `MemoryPolicy` protocol signature unchanged — P2 adds a new implementation
- `PersonaConfig` fields `database_url`, `graphiti_url` already exist
- Existing tests continue to pass against file-based fixtures

## Approaches Considered

### Approach A: Layered Manager with Dual Backends (Recommended)

`MemoryManager` owns both a SQLAlchemy async session and a Graphiti
client. It routes writes to the appropriate backend based on content
type: operational facts → Postgres, semantic episodes → Graphiti.
`get_context()` merges both sources. `PostgresGraphitiMemoryPolicy`
delegates to `MemoryManager` internally.

**Pros:**
- Clean separation: consumers call `MemoryManager`, never touch raw
  clients directly
- Matches the three-tier hierarchy from perplexity §1.2 exactly
- `export_memory()` has access to both backends for complete snapshots
- Graceful degradation: if Graphiti is unavailable, Postgres still works

**Cons:**
- Two infrastructure dependencies (Postgres + Neo4j) required for full
  functionality
- MemoryManager becomes a coordination point — must handle partial
  failures

**Effort:** L

### Approach B: Postgres-First with Graphiti Facade

All memory goes through Postgres (operational + embeddings via pgvector).
Graphiti client is wrapped behind a thin facade that's called only for
entity extraction and relationship building, not as a primary store.
Search uses pgvector for similarity, Graphiti for graph traversal.

**Pros:**
- Single primary datastore simplifies operations
- ParadeDB's BM25 + vector capabilities reduce need for separate search
- Fewer failure modes — Graphiti outage doesn't affect reads

**Cons:**
- Loses Graphiti's temporal knowledge graph strengths (episodic memory,
  entity evolution over time)
- Graph traversal queries require Neo4j anyway, so the dependency remains
- Diverges from the designed architecture in bootstrap spec

**Effort:** M

### Approach C: Event-Sourced Memory Log

All memory writes append to an immutable event log in Postgres.
Materialized views derive current state. Graphiti subscribes to the
event stream for entity extraction. Full audit trail and replayability.

**Pros:**
- Complete history of every memory mutation
- Replayable: can rebuild Graphiti index from event log
- Natural fit for temporal queries ("what did the agent know on date X?")

**Cons:**
- Significant additional complexity (event schema, projections, compaction)
- Overkill for current scale — the assistant serves one user per persona
- Materialized view maintenance adds operational burden
- Graphiti already has its own temporal model

**Effort:** XL

### Selected Approach

**Approach A: Layered Manager with Dual Backends** — selected because it
directly implements the three-tier hierarchy from perplexity §1.2,
maintains clean separation of concerns, and provides graceful
degradation when Graphiti is unavailable. The dual-backend complexity is
justified by the distinct strengths each brings: Postgres for fast
operational reads, Graphiti for semantic relationships and temporal
entity tracking.

## Dependencies

- **Requires**: P1.8 `capability-protocols` (archived) — MemoryPolicy protocol
- **Unblocks**: P7 `scheduler`, P8 `obsidian-vault`, P12 `delegation-context`

## Risks

1. **Neo4j availability** — Graphiti requires Neo4j. Mitigated by graceful
   degradation: `MemoryManager` operates in Postgres-only mode if
   `graphiti_url` is empty or Neo4j is unreachable.
2. **Schema evolution** — Alembic migrations must work with ParadeDB.
   Mitigated by testing against standard Postgres in CI (ParadeDB is a
   superset).
3. **Test isolation** — Tests must not require running Postgres/Neo4j.
   Mitigated by `FileMemoryPolicy` as test default + mock-based unit tests
   for MemoryManager + optional integration test markers.
