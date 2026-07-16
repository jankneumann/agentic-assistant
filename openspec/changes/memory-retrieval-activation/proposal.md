# Proposal: memory-retrieval-activation

## Why

The memory plumbing shipped in P2 (`memory-architecture`) and the
prepend hook shipped in P5 (`ms-graph-extension` D27) never met: all
four built-in `MemoryPolicy` implementations return `[]` from
`get_recent_snippets()` (`src/assistant/core/capabilities/memory.py`),
so no live retrieval ever reaches a harness. The MSAF harness dutifully
prepends an empty list (i.e. nothing); the DeepAgents harness does not
consume `MemoryPolicy` at all. Nothing writes turn history back either
— `MemoryManager.store_interaction` exists but has no caller on the
conversation path. Net effect: a persona with a fully configured
Postgres + Graphiti stack gets exactly the same (amnesiac) prompt as a
persona with nothing.

This phase activates the retrieval and capture loop:

- **Retrieval**: `PostgresGraphitiMemoryPolicy.get_recent_snippets`
  returns real snippets from `MemoryManager` (recent facts,
  high-confidence preferences, recent interaction summaries, plus
  Graphiti semantic search when configured — degrading to
  Postgres-only). `FileMemoryPolicy.get_recent_snippets` returns
  bounded excerpts of the persona's `memory.md` so file-only personas
  participate too.
- **Parity**: the DeepAgents harness consumes `MemoryPolicy` at
  `create_agent` time exactly like MSAF does (prepend under
  `## Recent context`), closing the documented asymmetry.
- **Capture**: after a successful `invoke` / `astream_invoke`, SDK
  harnesses store a one-line interaction summary via the policy's new
  `record_interaction` (backed by `MemoryManager.store_interaction`
  for database personas; no-op otherwise). Failures are swallowed with
  a warning — memory must never break a conversation.

## What Changes

1. **`MemoryManager.get_recent_snippets(persona, role, limit=10)`**
   (`src/assistant/core/memory.py`) — new async method returning a
   bounded `list[str]`: durable snippets (facts by `updated_at` DESC,
   preferences by `confidence` DESC, Graphiti semantic results for the
   role when configured) budgeted against recent interaction
   summaries. Instrumented with `@trace_memory_op("snippets")`.
   Graphiti failures degrade to Postgres-only with a WARNING
   (mirroring `get_context`).

2. **`_VALID_OPS` grows `"snippets"`**
   (`src/assistant/telemetry/providers/base.py`) — the new
   `MemoryManager` method needs a distinct op value so dashboards can
   tell retrieval-for-prepend apart from `get_context`.

3. **`PostgresGraphitiMemoryPolicy.get_recent_snippets`** — replaces
   the `return []` stub with a sync facade over the async manager (see
   design.md D1 for the bridge). Any backend failure returns `[]` with
   a WARNING. `export_memory_context` is refactored onto the same
   `_run_blocking` helper.

4. **`FileMemoryPolicy.get_recent_snippets`** — returns the persona's
   `memory.md` split into `## ` sections, most recent (last) section
   first, capped at `limit` sections and 4000 total characters.

5. **`MemoryPolicy` protocol grows `record_interaction`** — async,
   best-effort post-turn write. `PostgresGraphitiMemoryPolicy`
   delegates to `MemoryManager.store_interaction` with a
   whitespace-normalized, length-capped turn summary;
   `FileMemoryPolicy` and `HostProvidedMemoryPolicy` are no-ops.

6. **DeepAgents harness memory parity**
   (`src/assistant/harnesses/sdk/deep_agents.py`) — `create_agent`
   composes `system_prompt` as `## Recent context` + snippets +
   composed prompt (unchanged prompt when snippets are empty),
   resolving the policy via `CapabilityResolver` (or an injected
   `memory_policy` kwarg for tests, mirroring MSAF). `InMemorySaver`
   checkpointing is untouched.

7. **Post-turn capture in both SDK harnesses** — a shared
   `SdkHarnessAdapter._capture_interaction` helper
   (`src/assistant/harnesses/base.py`) awaits
   `record_interaction` after a successful `invoke`; streaming paths
   capture the concatenated `TextDelta` text just before the terminal
   success `RunFinished`. All failures are swallowed with a WARNING.

8. **Tests** — mock-based (no live Postgres/FalkorDB): snippet happy
   path, empty-DB path, Graphiti-down degradation, budget split, file
   policy bounds, DeepAgents prompt injection (present / absent),
   capture on success, capture swallowed on failure, no capture on
   agent failure, sync/async bridge from inside and outside a running
   loop.

9. **Docs** — CLAUDE.md "What's Not Yet Wired" MSAF/memory bullet
   rewritten to reflect the new reality.

## Out of Scope

- **Durable session persistence** — owned by the parallel
  `capability-protocols-v2` work (P24). This change is retrieval +
  capture only; `InMemorySaver` and thread-id semantics are untouched.
- **Mid-turn retrieval / structured memory hooks in MSAF** — still
  blocked on an `agent-framework` SDK injection point (see the
  ms-agent-framework-harness spec follow-up note; prepend remains the
  mechanism).
- **Graphiti episode write-back on capture** — `store_episode`
  ingestion of turn content is a natural follow-up once capture
  volume/shape is observed; P21 writes only the `interactions` row.
- **Host harnesses** — `HostProvidedMemoryPolicy` stays empty-list /
  no-op; the host owns memory for Claude Code / Codex exports.
