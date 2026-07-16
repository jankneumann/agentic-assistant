# Tasks

## 1. MemoryManager retrieval

- [x] 1.1 Add `MemoryManager.get_recent_snippets(persona, role,
  limit=10)` to `src/assistant/core/memory.py` — bounded reads of
  `memory` / `preferences` / `interactions` plus inlined Graphiti
  search with WARNING-degradation; durable/recent budget split with
  backfill (design D2).
- [x] 1.2 Instrument with `@trace_memory_op("snippets")` and add
  `"snippets"` to `_VALID_OPS` in
  `src/assistant/telemetry/providers/base.py` (design D6).

## 2. MemoryPolicy implementations

- [x] 2.1 Add `_run_blocking` sync/async bridge helper to
  `src/assistant/core/capabilities/memory.py` (design D1) and refit
  `PostgresGraphitiMemoryPolicy.export_memory_context` onto it.
- [x] 2.2 Implement `PostgresGraphitiMemoryPolicy.get_recent_snippets`
  — delegate to `MemoryManager.get_recent_snippets` through
  `_run_blocking`; degrade to `[]` with WARNING on any failure.
- [x] 2.3 Implement `FileMemoryPolicy.get_recent_snippets` — reversed
  `## ` sections of `persona.memory_content`, capped at `limit`
  sections and `_FILE_SNIPPET_CHAR_BUDGET` (4000) chars (design D5).
- [x] 2.4 Extend the `MemoryPolicy` protocol with async
  `record_interaction`; implement on all three built-ins
  (Postgres → `store_interaction` with capped summary + 
  `{"source": "post_turn_capture"}` metadata; File / HostProvided →
  no-op) (design D3/D4).

## 3. Harness wiring

- [x] 3.1 Add `SdkHarnessAdapter._capture_interaction` to
  `src/assistant/harnesses/base.py` — resolves the concrete harness's
  memory policy, awaits `record_interaction`, swallows every failure
  with a WARNING.
- [x] 3.2 DeepAgents: add `memory_policy` / `memory_snippet_limit`
  kwargs, `_resolve_memory_policy`, and `_compose_system_prompt`
  (prepend `## Recent context` when snippets exist; unchanged prompt
  otherwise); use it in `create_agent`; propagate kwargs in
  `spawn_sub_agent`. Keep `InMemorySaver` unchanged (design D7).
- [x] 3.3 DeepAgents: post-turn capture in `invoke` (extracted
  response) and `astream_invoke` (accumulated `TextDelta` text,
  before the terminal success `RunFinished`).
- [x] 3.4 MSAF: post-turn capture in `invoke` and `astream_invoke`
  (same placement rules).

## 4. Tests (mock-based, no live Postgres/FalkorDB)

- [x] 4.1 `tests/test_memory_manager.py` — snippets happy path,
  empty-DB, budget split, recent backfill, non-positive limit.
- [x] 4.2 `tests/test_memory_manager_graphiti.py` — semantic results
  included; ConnectionError degrades to Postgres-only with WARNING.
- [x] 4.3 `tests/test_memory_policy.py` — file policy: empty content,
  most-recent-first ordering, limit cap, char budget, no-headings
  fallback, no-op `record_interaction`.
- [x] 4.4 `tests/test_postgres_memory_policy.py` — bridge from outside
  and inside a running loop, backend-failure degradation to `[]`,
  `record_interaction` delegation + bounded summary + propagation.
- [x] 4.5 `tests/test_harnesses.py` — DeepAgents prompt contains
  `## Recent context` with snippets, unchanged when empty, default
  file-policy no-injection, capture on success, capture failure
  swallowed with WARNING, no capture on agent failure.
- [x] 4.6 `tests/test_harness_ms_agent_fw.py` — MSAF capture on
  success, swallowed failure, no capture on agent failure.
- [x] 4.7 `tests/harnesses/test_deep_agents_astream.py` — streaming
  capture of concatenated text on success; no capture on error.
- [x] 4.8 `tests/telemetry/test_protocol.py` +
  `tests/telemetry/test_noop.py` — `"snippets"` in the op enum.

## 5. Docs & specs

- [x] 5.1 Spec deltas: memory-policy (protocol MODIFIED + retrieval /
  capture ADDED), harness-adapter (DeepAgents injection + capture
  ADDED), ms-agent-framework-harness (follow-up prose MODIFIED),
  observability (op enum MODIFIED).
- [x] 5.2 Update CLAUDE.md "What's Not Yet Wired" MSAF/memory bullet.

## 6. Quality gates

- [x] 6.1 `uv run pytest tests/ -q` — 1011 passed, 3 skipped.
- [x] 6.2 `uv run ruff check src tests` — clean.
- [x] 6.3 `uv run mypy src tests` — 0 issues in 168 files.
- [x] 6.4 `openspec validate memory-retrieval-activation --strict`.
