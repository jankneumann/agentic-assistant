# delegation-context — Rich Delegation Context (P12)

## Why

Delegation today hands a sub-agent a bare task string. The sub-agent
starts blind: it does not know who delegated, through which chain the
authority arrived, what the parent conversation was about, what memory
is relevant, or what bounds it operates under (perplexity §3.3 /
§8.11; roadmap P12). The P25 `AgentIdentity` made chains attributable
for guardrails, but none of that context reaches the sub-agent's
prompt. There is also no cycle protection (A→B→A loops burn the depth
budget before failing), no parallel fan-out, no way to observe or
cancel an in-flight delegation, and sub-role selection is always
manual (`/delegate <role> <task>`), though the §5 P1 router was
planned from the start.

## What Changes

- **`DelegationContext` dataclass** (`delegation/context.py`):
  parent_role, the CHILD `AgentIdentity` (the delegation chain lives
  on the P25 identity — never duplicated), memory snippets fetched
  under the SUB-role, an optional parent-supplied conversation
  summary, and a constraints map (`max_depth_remaining`,
  `deadline_seconds`, `allowed_tools`). Rendered as a
  `## Delegation context` prompt block mirroring the D27
  `## Recent context` prepend; empty sections omitted.
- **`spawn_sub_agent` contract extended additively**: an optional
  `context` keyword (default `None` = pre-P12 behavior). Both SDK
  harnesses thread it to the sub-harness constructor and prepend the
  rendered block ahead of the recent-context section. The spawner
  falls back to the pre-P12 call shape (with a WARNING) for adapters
  that predate the keyword.
- **Cycle detection**: a sub-role already present in the identity's
  delegation chain — including self-delegation — is denied with
  `PermissionError` + audit record, unless the parent role opts in
  via `delegation.allow_recursive: true` (off by default).
- **`delegate_parallel`**: semaphore-bounded fan-out of
  `(sub_role, task)` pairs with per-task error isolation — each pair
  yields a `DelegationOutcome` marker (success / error / cancelled)
  in input order; one failure never aborts siblings.
- **Monitoring & cancellation**: an in-process registry of
  `DelegationRecord`s (id, sub_role, task, started_at, status,
  duration) behind `list_active()` / `get_record()` /
  `cancel(delegation_id)`; `deadline_seconds` is enforced via
  `asyncio.timeout`.
- **Delegation analytics WITHOUT new tables** (deviation from the old
  roadmap text — recorded in design.md): outcomes ride the existing
  `trace_delegation` span (P4) plus a best-effort one-line
  `[delegation]`-prefixed `record_interaction` summary under the
  parent role (no-op for file-backed memory); `analytics()` serves
  live in-process counters.
- **`delegation/router.py`**: deterministic-first intent
  classification for `delegate_auto(task)` — keyword/preferred-tool
  scoring over the candidate roles; OPTIONAL model-assisted
  classification gated behind an explicit `router` consumer binding
  (P19), deterministic fallback always.

## Impact

- Affected specs: `delegation-spawner` (ADDED requirements),
  `harness-adapter` (MODIFIED SDK adapter contract — additive
  `context` parameter on `spawn_sub_agent`).
- Affected code: `src/assistant/delegation/{context,router,spawner}.py`,
  `src/assistant/harnesses/base.py`,
  `src/assistant/harnesses/sdk/{deep_agents,ms_agent_fw}.py`,
  `src/assistant/telemetry/decorators.py` (kwargs pass-through only),
  `roles/_template/role.yaml`, `personas/_template/persona.yaml`.
- Backward compatible: no-context spawns are byte-identical to
  pre-P12 prompts; `delegate(sub_role, task)` call sites unchanged;
  pre-P12 harness adapters keep working (context dropped with a
  WARNING). No DB migration.
