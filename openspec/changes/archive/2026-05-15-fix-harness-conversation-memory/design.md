# Design: fix-harness-conversation-memory

## Scope

This is a focused bug fix, not a feature. The substantive design
analysis lives in
[`proposal.md`](./proposal.md) — see *Approaches Considered* and
*Selected Approach*. This file captures the few decisions that
warrant explicit recording.

## D1. Why `InMemorySaver` is the right scope today

LangGraph offers three checkpointer flavors:

1. `InMemorySaver` — in-process, per-instance, ephemeral.
2. `SqliteSaver` — file-backed, per-process or shared via file path.
3. `PostgresSaver` — durable, cross-process, transactional.

The CLI's session lifetime is exactly one harness instance. There is
no cross-restart resume contract today and no other consumer of the
agent's state outside the REPL loop. `InMemorySaver` is the minimum
that satisfies the contract.

The P2 `memory-architecture` phase will introduce persona-keyed
Postgres for memory and conversation state. At that point, the
choice point is whether persona-level `ParadeDB`/`Postgres` becomes
the substrate for LangGraph's checkpointer (`PostgresSaver`) or
remains separate from agent-state persistence. Either way,
`InMemorySaver` here is forward-compatible: the swap is one line in
`create_agent`.

## D2. Why a UUID4 per harness, not per persona/session

Thread IDs scope conversation history. Three plausible scopes:

1. **Per harness instance**: a new UUID4 every `create_agent`. Matches
   the existing `/role <new>` rebuild semantics — role switches start
   a fresh conversation.
2. **Per persona**: stable across all roles for a persona. Would let
   `/role` switches preserve some shared history.
3. **Per session-id provided by the CLI**: requires the CLI to coin
   and manage ids.

Option 1 is the simplest and matches the existing intent: `/role
<new>` *already* destroys the previous agent (`cli.py:146-159`).
Preserving conversation across roles is a separate behavioral choice
that the repo hasn't made. The teacher role spec's "Method
Persistence Across Turns" requirement specifically calls out that
`/role <other>` clears teacher state — meaning roles are expected to
be conversation boundaries.

Option 2 would need a policy decision about cross-role memory that
the repo doesn't have yet. Option 3 leaks harness concerns into the
CLI.

Option 1 is reversible: if the repo later decides roles should share
memory, swap the UUID4 generation point from `create_agent` to a
session-level setup.

## D3. Why mock-driven tests for the plumbing + smoke-test for end-to-end

Five new tests cover the harness contract:

| Test | What it asserts |
|---|---|
| `test_create_agent_constructs_with_checkpointer` | `create_deep_agent` receives non-None `checkpointer` |
| `test_create_agent_passes_real_inmemorysaver_instance` | The kwarg is an actual `InMemorySaver`, not a Mock |
| `test_invoke_passes_thread_id_in_runnable_config` | `ainvoke` receives `config["configurable"]["thread_id"]` |
| `test_thread_id_is_stable_across_invocations_on_one_harness` | Two invokes on one harness use the same thread_id |
| `test_distinct_harnesses_get_distinct_thread_ids` | Two harnesses get distinct UUIDs |

I intentionally did NOT write a unit test that drives a real
`InMemorySaver` through full put/get round-trips. That requires
synthesizing the full `configurable` shape LangGraph's runnable
machinery sets up (`checkpoint_ns`, `checkpoint_id`, etc.), which
makes the test brittle to LangGraph internals.

The contract LangGraph owns is "given a checkpointer and a stable
thread_id, history is preserved." That contract is upstream-tested
in LangGraph's own suite. The contract *we* own is "the harness wires
those two things correctly." The five tests above prove that.

End-to-end verification lives at the smoke-test level: user runs the
teacher Feynman loop, observes Step 3 referencing Step 2's content.
That's the failing case from agentic-assistant#34 and the natural
acceptance test.

## D4. What this does not fix

- **MSAF harness**: `ms_agent_fw.py` uses a different SDK. The
  `harness-adapter` spec requirement added here applies to the
  abstract contract, but the MSAF implementation will need its own
  thread-state audit when it's wired into a persona. Tracked as
  out-of-scope per the issue.
- **Cross-restart resume**: `InMemorySaver` is per-process. If the
  CLI exits, the conversation is gone. P2 `memory-architecture`
  territory.
- **Concurrent invocations**: a single `DeepAgentsHarness` instance is
  invoked sequentially from the REPL. Concurrent fan-out (e.g.,
  parallel delegation) would share a thread, which may or may not be
  desired. Out of scope for this fix.
