# Design: memory-retrieval-activation

## D1. Async/sync bridge for the sync `MemoryPolicy` protocol

`MemoryPolicy.get_recent_snippets` is synchronous (protocol shape fixed
in P1.8/P5) while `MemoryManager` is async. The call site is the sync
`_compose_*` helper invoked from the **async** `create_agent` path, so
"there is a running event loop" is the hot path, not the edge case.

Chosen bridge (`_run_blocking` in
`src/assistant/core/capabilities/memory.py`):

- **No running loop** (sync CLI setup, sync tests): `asyncio.run(coro)`.
- **Inside a running loop**: submit `asyncio.run(coro)` to a
  single-worker `ThreadPoolExecutor` and block on `.result()`. Calling
  `loop.run_until_complete` on the already-running loop would raise /
  deadlock; the worker thread runs the coroutine on its own private
  loop instead.

Explicit consequences, accepted:

- The worker-thread path creates a **fresh event loop per call**, so
  loop-bound resources (asyncpg pooled connections in the cached
  `AsyncEngine`) cannot be assumed reusable across calls. Retrieval is
  therefore wrapped in a policy-level `try/except` that degrades to
  `[]` with a WARNING — a cross-loop pool error is a degraded-memory
  condition, never a fatal one. A loop-affine engine strategy (or
  `NullPool` for policy reads) is a follow-up if real usage shows churn.
- The call **blocks the running loop** for the duration of the DB
  round-trip. This is a `create_agent`-time cost (once per session /
  role switch), not a per-token cost; bounded queries (`LIMIT` on all
  three tables) keep it small.
- `export_memory_context` used the same pattern ad hoc
  (`asyncio.get_event_loop()` + `is_running()`); it now shares
  `_run_blocking`, which also removes the Python 3.12+
  `get_event_loop()` deprecation exposure.

Alternatives rejected:

- **Make the protocol async**: touches every implementer and consumer
  (including host-harness export paths) for no behavioral gain; the
  P24 capability-protocols-v2 effort owns protocol-shape evolution.
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
