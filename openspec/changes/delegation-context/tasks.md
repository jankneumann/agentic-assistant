# delegation-context — Tasks

## 1. DelegationContext + harness rendering

- [x] 1.1 `delegation/context.py`: frozen `DelegationContext`
      (parent_role, child `AgentIdentity`, memory_snippets,
      conversation_summary, constraints) + `render()` producing the
      `## Delegation context` block with empty sections omitted
- [x] 1.2 `SdkHarnessAdapter.spawn_sub_agent` gains additive
      `context: DelegationContext | None = None`
- [x] 1.3 DeepAgents harness: `delegation_context` constructor kwarg,
      block prepended ahead of `## Recent context` in
      `_compose_system_prompt`, threaded by `spawn_sub_agent`
- [x] 1.4 MSAF harness: same treatment in `_compose_instructions` +
      `spawn_sub_agent`
- [x] 1.5 Update in-tree test doubles to the new signature

## 2. Spawner: context, cycles, parallel, monitoring

- [x] 2.1 Context construction per hop (snippets under the SUB-role,
      limit 5, error-swallowed; constraints incl. max_depth_remaining)
- [x] 2.2 Signature-inspection fallback for pre-P12 adapters
- [x] 2.3 Cycle detection + `delegation.allow_recursive` opt-out,
      audited like depth denials
- [x] 2.4 `delegate_parallel` with semaphore + `DelegationOutcome`
      per-task isolation
- [x] 2.5 Monitoring registry: `DelegationRecord`, `list_active()`,
      `get_record()`, `cancel()`, bounded retention
- [x] 2.6 `deadline_seconds` enforcement via `asyncio.timeout`
- [x] 2.7 Analytics without tables: `analytics()` counters +
      `[delegation]` `record_interaction` summary on success
- [x] 2.8 `traced_delegation` kwargs pass-through (span unchanged)

## 3. Router

- [x] 3.1 `delegation/router.py`: deterministic scoring (name x3 /
      tools x2 / description x1, mutual-prefix token match), tie →
      candidate order, all-zero → `RoutingError`
- [x] 3.2 Model-assisted path gated on explicit `router` binding;
      `bind_langchain` transport; fallback-to-deterministic on any
      failure; injectable `model_invoker` (gate independent)
- [x] 3.3 `DelegationSpawner.delegate_auto` / `route_task`
- [x] 3.4 Template docs: `roles/_template/role.yaml`
      (`allow_recursive`), `personas/_template/persona.yaml`
      (`router` binding)

## 4. Tests + gates

- [x] 4.1 Context rendering (full / empty sections / no chain
      duplication) + both harnesses' prompt injection + no-context
      byte-identity
- [x] 4.2 Cycle rejection, self-delegation, `allow_recursive`
      override, cycle-before-depth ordering
- [x] 4.3 Parallel isolation, concurrency cap, empty input
- [x] 4.4 Monitoring: list_active, cancel (running / finished /
      unknown), deadline timeout, analytics counters, outcome
      summary under parent role
- [x] 4.5 Router: deterministic scoring, binding gate, mocked model
      path, garbage-reply + failure fallback, delegate_auto
      integration, spawner backward compat (legacy adapter)
- [x] 4.6 Gates: `uv run pytest tests/`, `ruff check src tests`,
      `mypy src tests`, `openspec validate delegation-context --strict`
