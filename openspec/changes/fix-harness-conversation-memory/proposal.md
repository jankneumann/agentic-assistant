# Proposal: fix-harness-conversation-memory

## Why

`DeepAgentsHarness.invoke` (`src/assistant/harnesses/sdk/deep_agents.py:62-72`)
invokes the agent with only the new turn's message and no thread
configuration. `create_deep_agent` in `create_agent` (line 54-60) is
constructed without a `checkpointer=`. Net effect: every CLI turn is a
fresh conversation. The agent has no memory of prior turns.

The harness's own docstring at line 64-69 hints at the design intent:

> Token usage is captured by the `@traced_harness` decorator [...]
> which keeps concurrent `asyncio.gather` invocations isolated and
> prevents prior-turn tokens from being summed once a
> **checkpointer-backed agent re-uses the same harness**.

— but the constructor never wires a checkpointer, so this behavior was
never actually realized. The gap is pre-existing from the P1 bootstrap
slice (2026-04-12) and stayed latent because every CLI test uses
`StubHarness` (no real `ainvoke`) and the one real-harness invoke test
(`test_invoke_returns_last_assistant_message_content`) used a
single-turn mock that asserts only on extraction, not on history
preservation.

The `add-teacher-role` smoke test (2026-05-14) was the first feature
to require multi-turn coherence as part of its core behavior, and the
agent self-reported the bug:

> *"I don't see any previous teaching method or topic established in
> our conversation history, so we're starting fresh."*

Filed as agentic-assistant#34.

This affects **every SDK role** — `chief_of_staff`, `researcher`,
`planner`, `writer`, `coder`, `teacher` — so the fix belongs at the
harness layer, not in any individual role.

## What Changes

1. **Construct `DeepAgentsHarness`'s agent with a checkpointer.**
   Pass `checkpointer=InMemorySaver()` (from
   `langgraph.checkpoint.memory`) into `create_deep_agent`. The
   `deepagents` 0.5.2 API already accepts this kwarg (verified via
   `inspect.signature(create_deep_agent)`), so no upstream dependency
   change is required. `InMemorySaver` is ephemeral per-process —
   appropriate for the CLI's single-session lifetime and not requiring
   any I/O or external dependency. Persistent storage (Postgres-backed
   checkpointer keyed on persona) is left to the P2
   `memory-architecture` phase.

2. **Generate a `thread_id` per `DeepAgentsHarness` instance.** A
   `uuid.uuid4()` is captured in `create_agent` and stashed on the
   harness as `self._thread_id`. The harness's lifetime IS the
   conversation's lifetime: `create_agent` is called once per REPL
   session, and `/role <name>` rebuilds the harness (see
   `cli.py:146-159`), which naturally starts a fresh conversation
   thread — matching the intent of the role-switch command.

3. **Pass the `thread_id` in invoke config.** `invoke` augments its
   call to `agent.ainvoke` with
   `config={"configurable": {"thread_id": self._thread_id}}`. This is
   the standard LangGraph mechanism for binding an invocation to a
   checkpointed thread; combined with step 1, it gives the agent a
   coherent view of prior user/assistant messages on every turn.

4. **Regression test coverage** (`tests/test_harnesses.py`):
   - `test_invoke_preserves_history_across_turns`: two `invoke` calls
     on the same harness with a real `InMemorySaver` and a stub model
     that records its `messages` input — the second call's input MUST
     contain both the first turn's user message and the first turn's
     assistant message.
   - `test_create_agent_assigns_fresh_thread_id_per_harness`: two
     distinct `DeepAgentsHarness` instances assign distinct
     `_thread_id` values, and the second instance's `ainvoke` does not
     see the first instance's messages.
   - The existing single-turn extraction test
     (`test_invoke_returns_last_assistant_message_content`) stays as a
     pure-extraction guard — separate concern.

5. **Spec delta** (`harness-adapter/spec.md`): add a new
   "Multi-Turn Conversation Memory" requirement covering the three
   contractual points above (checkpointer present at construction,
   thread_id stable across invocations on a single harness, fresh
   thread per harness instance).

## Approaches Considered

### Approach 1: `InMemorySaver` + per-harness `uuid4` thread *(Recommended)*

**Description**: As described in *What Changes*. Wire `InMemorySaver`
at `create_agent` time, assign a `uuid4` thread_id once, pass it on
every invoke.

**Pros**:
- Zero new dependencies — `langgraph-checkpoint` 4.0.1 is already in
  the venv via `deepagents`'s transitive deps.
- Minimal API surface change: harness keeps its existing
  `create_agent(tools, extensions)` and `invoke(agent, message)`
  signatures.
- `/role <new>` rebuild semantics get the right behavior for free: a
  fresh harness instance ⇒ fresh thread ⇒ fresh conversation. Matches
  the existing intent of `/role`.

**Cons**:
- In-process only. If the CLI crashes mid-session, conversation is
  lost. Acceptable for the CLI's single-session use case; the
  memory-architecture phase will introduce a persistent checkpointer
  when persona-level Postgres lands.
- Concurrent `asyncio.gather` invocations on the same harness instance
  would now share a thread — but the existing harness pattern is
  one-agent-per-REPL-turn, so this is not a real concern today.

**Effort**: S (≤10 LoC + tests)

### Approach 2: Pass message history explicitly on each invoke

**Description**: Keep `ainvoke` stateless; the CLI tracks the message
list itself and re-sends the full history each turn.

**Pros**:
- No new library state. The history is just a Python list owned by
  the CLI.

**Cons**:
- Reinvents what LangGraph's checkpointer already does, and does it
  worse — the agent's internal state (tool calls, todos,
  intermediate-result messages) is not in the CLI's view, so the CLI
  cannot serialize it correctly. The model would lose its tool-call
  trace between turns.
- Requires the CLI to know harness-internal message shapes. That
  couples the CLI to the harness's choice of agent framework, which
  the abstract `HarnessAdapter` contract was specifically designed to
  avoid.
- Doesn't help the MSAF harness or any future SDK harness; each would
  need to reinvent its own history tracking.

**Effort**: M (CLI surgery + per-harness shape knowledge)

### Approach 3: Defer to memory-architecture phase

**Description**: Wait for P2's persistent checkpointer.

**Pros**:
- No interim solution to migrate away from later.

**Cons**:
- The teacher role is unusable until P2 lands, which is several
  phases out. P2 has substantial scope (persona-keyed Postgres,
  ParadeDB integration) and timeline uncertainty. The repo loses a
  feature it just shipped, indefinitely.
- The ergonomic gap is severe: every multi-turn CLI session today is
  broken in the same way, not just teacher.

**Effort**: 0 now, but blocks #34 until P2.

## Selected Approach

**Approach 1** — `InMemorySaver` + per-harness `uuid4` thread.

The change is small, additive, and correctly bounded to the harness
layer where the conversation contract belongs. P2's persistent
checkpointer can later swap `InMemorySaver` for a Postgres-backed
saver without touching `invoke` or any role.

Approach 2 leaks harness internals into the CLI and discards the
agent's intermediate state. Approach 3 leaves the teacher role and
every other multi-turn use case broken until a much larger phase
lands.

## Out of Scope

- **MSAF harness conversation memory.** The
  `MsAgentFrameworkHarness` (`src/assistant/harnesses/sdk/ms_agent_fw.py`)
  uses a different SDK with different threading primitives. Whether
  `agent_framework.Agent` carries thread state internally or also
  needs explicit wiring is a separate investigation. The
  `harness-adapter` spec requirement added here applies to the
  general harness contract, but the MSAF *implementation* will be
  audited under a follow-on issue.
- **Persistent (cross-restart) checkpointing.** A Postgres-backed
  checkpointer keyed on persona is appropriate for the P2
  `memory-architecture` phase, when persona-level storage is wired.
  In-process `InMemorySaver` is the right scope for the present CLI.
- **Replay / time-travel UI.** LangGraph's checkpointer supports
  rewinding to a prior state, but there's no REPL command to surface
  that, and there's no demand for it today. Tracked as a possible
  future enhancement.
- **Concurrent-invocation thread-safety.** A single
  `DeepAgentsHarness` instance is invoked sequentially from the REPL
  loop. If we later expose concurrent invocations (e.g., async
  fan-out from a host harness), thread-safety becomes a real
  question.
