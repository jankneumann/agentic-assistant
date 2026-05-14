# Tasks

## 1. Harness implementation

- [x] 1.1 Import `InMemorySaver` from `langgraph.checkpoint.memory` and
  `uuid4` from `uuid` at the top of
  `src/assistant/harnesses/sdk/deep_agents.py`.
- [x] 1.2 In `DeepAgentsHarness.__init__`, initialize
  `self._thread_id: str = ""` (assigned at `create_agent` time).
- [x] 1.3 In `DeepAgentsHarness.create_agent`, set
  `self._thread_id = str(uuid4())` before constructing the agent.
- [x] 1.4 Pass `checkpointer=InMemorySaver()` to `create_deep_agent`
  alongside the existing kwargs.
- [x] 1.5 In `DeepAgentsHarness.invoke`, pass
  `config={"configurable": {"thread_id": self._thread_id}}` as the
  second positional argument (or kwarg) to `agent.ainvoke`.
- [x] 1.6 Update the `invoke` docstring to reflect the new reality —
  checkpointer is now real, thread_id binds the call to the
  harness-lifetime thread.

## 2. Regression tests

- [x] 2.1 Add `test_create_agent_constructs_with_checkpointer`,
  `test_create_agent_passes_real_inmemorysaver_instance`, and
  `test_invoke_passes_thread_id_in_runnable_config` to
  `tests/test_harnesses.py` — together they prove the plumbing
  contract (checkpointer wired, thread_id passed on every invoke).
- [x] 2.2 Add `test_thread_id_is_stable_across_invocations_on_one_harness`
  and `test_distinct_harnesses_get_distinct_thread_ids` — together
  they prove the lifetime contract (thread stable on a single
  harness, fresh per instance).
- [x] 2.3 Update the four existing `_FakeAgent.ainvoke` stubs to
  accept the new `config=None` kwarg; the existing single-turn
  extraction test still passes (checkpointing is additive).

## 3. Spec delta

- [x] 3.1 Author
  `openspec/changes/fix-harness-conversation-memory/specs/harness-adapter/spec.md`
  with one `## ADDED Requirements` block containing the new
  "Multi-Turn Conversation Memory" requirement plus four
  scenarios (checkpointer present at construction, thread_id in
  invoke config, two-turn history visible, distinct harnesses).
- [x] 3.2 Validate with `openspec validate
  fix-harness-conversation-memory --strict` — clean on first
  pass (lead-with-SHALL pattern followed per G5).

## 4. Quality gates

- [x] 4.1 `uv run pytest tests/` — 807 passed, 3 skipped (+5 new).
- [x] 4.2 `uv run ruff check src tests` — clean.
- [x] 4.3 `uv run mypy src tests` — 0 issues in 144 files.
- [x] 4.4 `openspec validate fix-harness-conversation-memory --strict`
  — valid.

## 5. Smoke test

- [ ] 5.1 Run the teacher Feynman smoke test (`uv run assistant -p
  personal -r teacher --method feynman`) for a multi-turn dialog
  (Step 1 → user explanation → Step 3). Confirm the agent's Step 3
  response references the user's explanation from Step 2 (i.e.,
  history is actually preserved, not just plumbed).
- [ ] 5.2 Tick `add-teacher-role` task 6.3 (manual smoke test) if
  this run confirms multi-turn coherence — closes that remaining
  loose end.

## 6. Land the plane

- [ ] 6.1 Commit with `fix(harness-adapter): wire conversation memory
  via InMemorySaver + per-harness thread_id (#34)`.
- [ ] 6.2 Push to origin and verify `git status` shows up-to-date
  with origin.
- [ ] 6.3 Close agentic-assistant#34 with a reference to the commit
  and the smoke-test outcome.
- [ ] 6.4 Archive this change (`/openspec-archive-change
  fix-harness-conversation-memory`) once the smoke test passes.
