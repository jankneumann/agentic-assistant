# Design: memory-retrieval-activation

## D1. Async retrieval at the protocol level; bridge only at sync edges

**As amended by the capability-protocols-v2 (P24) owner review verdict
C8, 2026-07-16.** The original P21 design kept
`MemoryPolicy.get_recent_snippets` synchronous (protocol shape fixed
in P1.8/P5) and bridged to the async `MemoryManager` with a
`_run_blocking` helper (worker-thread `asyncio.run` when a loop was
already running). The owner review rejected that trade: the call site
is the `_compose_*` helper on the **async** `create_agent` path, so
the worker-thread bridge sat on the hot path — a fresh event loop per
call (defeating asyncpg pool reuse), a blocked running loop, and a
sync protocol shape that P19+ consumers would have built on.

Final shape:

- **`get_recent_snippets` is `async def` on the protocol and all
  implementations.** `PostgresGraphitiMemoryPolicy` awaits
  `MemoryManager.get_recent_snippets` directly on the caller's loop;
  `FileMemoryPolicy` / `HostProvidedMemoryPolicy` are trivial async
  defs. Both SDK harness composition helpers
  (`MSAgentFrameworkHarness._compose_instructions`,
  `DeepAgentsHarness._compose_system_prompt`) became async and are
  awaited from `create_agent`.
- **`_run_blocking` survives only for true sync edges** — today the
  sync `export_memory_context`, consumed by host-harness
  `export_context` and the CLI `export` command. Bridge at the edge,
  never inside an implementation's retrieval path. Its two branches
  are unchanged: `asyncio.run` off-loop; single-worker
  `ThreadPoolExecutor` + `asyncio.run` on-loop (a fresh loop per call,
  so loop-bound resources are not reusable there — acceptable for the
  rare export path).
- The policy-level `try/except` that degrades retrieval failures to
  `[]` with a WARNING is retained unchanged — a down backend is a
  degraded-memory condition, never a fatal one.
- The former "bridges from inside a running event loop" test moved to
  the sync edge (`export_memory_context` in
  `tests/test_postgres_memory_policy.py`); the retrieval tests now
  simply await the policy.

Alternatives rejected:

- **Keep the sync protocol + hot-path bridge** (original D1): rejected
  by the P24 owner review — parallel phases (P19 model routing, P22)
  must not inherit a sync seam that immediately needs re-widening.
- **`asyncio.create_task` fire-and-forget retrieval**: retrieval MUST
  complete before the prompt is composed — it cannot be detached.

## D2. Snippet composition and budget split

`MemoryManager.get_recent_snippets` composes two buckets:

- **Durable** — facts (`memory` table, `updated_at` DESC), preferences
  (`confidence` DESC), then Graphiti semantic search on the role name
  when configured (same query key `get_context` uses; failures degrade
  with a WARNING).
- **Recent** — interaction summaries (`created_at` DESC).

Budget: durable gets the ceiling half of `limit`; recent fills the
remainder; whichever bucket under-fills, the other backfills up to
`limit`. Rationale: with a naive priority list, ten stored facts would
permanently squeeze out interaction recency (or vice versa); the split
guarantees both durable knowledge and recent activity appear whenever
both exist, and the backfill keeps small memories from wasting budget.
All three SQL reads are `LIMIT limit` so the query cost is bounded by
the snippet budget.

## D3. Post-turn capture: awaited-inline, error-swallowed (not detached)

"Fire-and-forget" is implemented as **awaited but exception-isolated**
(`SdkHarnessAdapter._capture_interaction`), not as a detached
`asyncio.create_task`:

- The CLI drives each turn with `asyncio.run(...)`; a detached task
  would be destroyed when the per-turn loop closes — silently lossy
  and untestable.
- Awaiting keeps ordering deterministic for tests and for the
  `trace_memory_op("interaction_write")` span that rides on
  `MemoryManager.store_interaction`.
- The contract users care about — "memory failures must never break a
  conversation" — is delivered by the `except Exception: log WARNING`
  isolation, not by detachment. Latency cost is one bounded INSERT on
  the success path.

Streaming paths capture the concatenated `TextDelta` text and MUST do
so **before** yielding the terminal success `RunFinished`: consumers
typically close the generator after the terminal event, and code after
the final `yield` is skipped when `aclose()` throws `GeneratorExit`
into the suspended generator. Error and disconnect paths do not
capture (a failed turn produced no assistant response worth indexing).

Division of responsibility: the **policy** (`record_interaction`) lets
backend errors propagate; the **harness helper** owns swallow-and-warn.
This keeps the policy honestly testable and gives every harness one
uniform failure boundary.

## D4. Summary shape stored on capture

`store_interaction` receives
`"user: <excerpt> | assistant: <excerpt>"` with each side
whitespace-normalized and capped at 240 chars, plus
`metadata={"source": "post_turn_capture"}`. The summary is a retrieval
cue (it feeds back into `get_recent_snippets` as a "recent" bucket
line), not a transcript; full-fidelity logging belongs to
observability, and durable session state belongs to P24.

## D5. FileMemoryPolicy bounds

`memory.md` is treated as append-ordered: later `## ` sections are more
recent, so sections are emitted most-recent-first (reversed document
order). Two caps: at most `limit` sections AND at most 4000 total
characters (`_FILE_SNIPPET_CHAR_BUDGET`), with the section that crosses
the budget truncated to fit. Content before the first heading (or a
file with no headings) forms a single section. This keeps the
`## Recent context` block bounded even for personas with a large
hand-curated memory file. `record_interaction` is a no-op — memory.md
is user-curated; the harness never appends to it.

## D6. Telemetry op `"snippets"`

`get_recent_snippets` is a distinct `MemoryManager` method and gets a
distinct `trace_memory_op` op value rather than reusing `"context"`:
dashboards need to separate the once-per-session prepend retrieval
from `get_context` calls, and the observability spec's op enum is
defined as "each corresponding to a MemoryManager method". The Graphiti
call inside is NOT separately instrumented (req observability.6 —
exactly one span per manager method), which is also why the method
inlines the Graphiti try/except instead of calling `self.search`.

## D7. DeepAgents parity mechanics

DeepAgents gains the same constructor injection surface as MSAF
(`memory_policy`, `memory_snippet_limit` keyword-only kwargs, defaults
preserved so `create_harness(persona, role, name)` is unchanged) and
the same resolution order (injected policy → `CapabilityResolver`
which picks `PostgresGraphitiMemoryPolicy` when `database_url` is set,
`FileMemoryPolicy` otherwise). The prepend format is byte-identical to
MSAF's D27 format (`## Recent context\n\n<snippets joined by blank
lines>\n\n<composed prompt>`). `spawn_sub_agent` propagates the
injected policy so sub-agents share the parent's memory configuration.
`InMemorySaver` checkpointing and thread-id semantics are untouched
(P24 owns durable sessions).
