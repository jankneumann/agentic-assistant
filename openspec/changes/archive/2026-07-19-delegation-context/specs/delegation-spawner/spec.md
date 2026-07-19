# delegation-spawner Specification (delta)

## ADDED Requirements

### Requirement: Delegation Context Construction and Threading

The `DelegationSpawner.delegate()` method SHALL construct a
`DelegationContext` for every hop that passes the ACL, cycle, depth,
and guardrail checks, and SHALL pass it to
`harness.spawn_sub_agent(..., context=...)`. The context MUST carry:
the parent role name; the CHILD `AgentIdentity` derived via
`identity.delegate_to(sub_role)` (the delegation chain is read from
the identity — the context type MUST NOT define its own chain field);
memory snippets fetched under the SUB-role via
`MemoryPolicy.get_recent_snippets` (an injected policy or one lazily
resolved via `CapabilityResolver`; retrieval failures MUST degrade to
an empty snippet tuple without failing the delegation); the optional
caller-supplied `conversation_summary`; and a constraints map
containing `max_depth_remaining` (the persona's `max_chain_depth`
minus the child chain depth, omitted when the ceiling is unlimited)
plus `deadline_seconds` / `allowed_tools` when supplied by the
caller. For harness adapters whose `spawn_sub_agent` does not accept
a `context` parameter (pre-P12 signature), the spawner SHALL fall
back to the positional pre-P12 call — dropping the context for that
hop with a WARNING — rather than raising `TypeError`.

#### Scenario: Context carries child identity and sub-role snippets

- **WHEN** `delegate("writer", task, conversation_summary="s")` is
  awaited on a spawner whose parent role is `researcher` and whose
  memory policy returns `["m1", "m2"]`
- **THEN** the harness MUST receive a context whose `parent_role` is
  `"researcher"`, whose identity has `role == "writer"` and chain
  `("researcher",)`, whose snippets were fetched with the SUB-role,
  and whose `conversation_summary` is `"s"`

#### Scenario: Snippet retrieval failure degrades to empty

- **WHEN** the memory policy raises during snippet retrieval
- **THEN** the delegation MUST still complete and the context's
  `memory_snippets` MUST be empty

#### Scenario: Pre-P12 adapter still works without context

- **WHEN** the harness's `spawn_sub_agent` signature has no `context`
  parameter
- **AND** `delegate("writer", "t")` is awaited
- **THEN** the spawn MUST be invoked with the pre-P12 argument shape
  and the delegation MUST succeed

### Requirement: Delegation Cycle Detection

The `DelegationSpawner.delegate()` method SHALL reject a hop whose
sub-role equals the acting identity's role (self-delegation) or
already appears in `identity.delegation_chain`, raising
`PermissionError` with a reason naming the cycle and the
`allow_recursive` override, and emitting a guardrail audit record
with a deny decision — unless the parent role's `delegation:` section
sets `allow_recursive: true` (default false). The cycle check SHALL
run after the `allowed_sub_roles` / persona-availability `ValueError`
checks and BEFORE the chain-depth ceiling and
`check_delegation` guardrail call; the depth ceiling still applies
when recursion is allowed.

#### Scenario: Sub-role already in the chain is denied

- **WHEN** the spawner's identity carries chain `("writer",)` and
  `delegate("writer", task)` is called for an allowed sub-role
- **THEN** `PermissionError` MUST be raised naming the cycle
- **AND** `spawn_sub_agent` MUST NOT be called
- **AND** an audit record with a deny decision MUST be emitted

#### Scenario: Self-delegation is denied

- **WHEN** a spawner acting as role `researcher` calls
  `delegate("researcher", task)` and the ACL allows it
- **THEN** `PermissionError` MUST be raised naming the cycle

#### Scenario: allow_recursive permits the repeat hop

- **WHEN** the parent role's delegation config sets
  `allow_recursive: true`
- **AND** the sub-role already appears in the chain
- **THEN** the delegation MUST proceed (subject to the unchanged
  depth ceiling and guardrail checks)

### Requirement: Parallel Delegation with Per-Task Isolation

The spawner SHALL provide
`delegate_parallel(tasks: Sequence[tuple[str, str]], *,
max_concurrent=None)` which fans the `(sub_role, task)` pairs out
concurrently under a semaphore sized to the parent role's
`delegation.max_concurrent` (narrowed further by the
`max_concurrent` argument when given, floor 1) so queued pairs wait
instead of tripping `delegate()`'s concurrency `RuntimeError`. Each
pair SHALL yield a `DelegationOutcome` marker — `status` of
`success` (with the result), `error` (with the exception class and
message), or `cancelled` — returned in input order; one pair's
failure MUST NOT abort the others. An empty input SHALL return an
empty list.

#### Scenario: One failing task does not abort siblings

- **WHEN** `delegate_parallel([(r, "good-1"), (r, "bad"), (r2, "good-2")])`
  is awaited and the `"bad"` spawn raises `ValueError`
- **THEN** the returned statuses MUST be
  `["success", "error", "success"]` in input order
- **AND** the error outcome MUST name `ValueError`

#### Scenario: Concurrency stays within the role ceiling

- **WHEN** the parent role's `max_concurrent` is 2 and five pairs are
  submitted
- **THEN** at most 2 spawns MUST be in flight at any moment
- **AND** all five outcomes MUST be `success`

### Requirement: Delegation Monitoring and Cancellation

The spawner SHALL track every `delegate()` call in an in-process
registry of `DelegationRecord`s (delegation id, sub-role, task,
started_at, status running/succeeded/failed/cancelled, finished_at,
duration) and SHALL expose `list_active()` (running records),
`get_record(id)`, and `cancel(id)`. `cancel` SHALL cancel the
delegation's asyncio task and return `True`; for unknown ids or
finished delegations it SHALL return `False` without error. A
`deadline_seconds` argument to `delegate()` SHALL be enforced via an
asyncio timeout — an overrunning delegation fails with
`TimeoutError` and its record is marked `failed`. Finished-record
retention SHALL be bounded (running records are never evicted).

#### Scenario: In-flight delegation is listed and cancellable

- **WHEN** a delegation is blocked in `spawn_sub_agent`
- **THEN** `list_active()` MUST return its running record
- **AND** `cancel(<id>)` MUST return `True`, the awaiting caller MUST
  observe `asyncio.CancelledError`, and the record's status MUST
  become `cancelled`

#### Scenario: Cancel of unknown or finished delegation returns False

- **WHEN** `cancel("no-such-id")` is called, or `cancel` targets an
  already-finished record
- **THEN** the return value MUST be `False`

#### Scenario: Deadline overrun fails the delegation

- **WHEN** `delegate(role, task, deadline_seconds=0.02)` is awaited
  and the spawn takes longer
- **THEN** `TimeoutError` MUST propagate and the record MUST be
  marked `failed`

### Requirement: Delegation Analytics Without New Tables

The spawner SHALL surface delegation analytics without introducing
database tables or migrations: (1) every delegation continues to emit
the existing `trace_delegation` span (vocabulary unchanged); (2) on
success the spawner SHALL store a one-line summary via the memory
policy's `record_interaction` under the PARENT role with a
`[delegation] <parent> -> <sub>: <task>` user-message prefix
(best-effort — failures are swallowed; file-backed memory no-ops);
(3) an `analytics()` method SHALL return in-process counters over the
registry: total, active, counts by status, counts by sub-role, and
average duration of finished delegations.

#### Scenario: Success stores a parent-role summary

- **WHEN** `delegate("writer", "draft the recap")` succeeds
- **THEN** `record_interaction` MUST be called once under the parent
  role with a user message starting `[delegation]` and containing the
  task
- **AND** a failed delegation MUST NOT store a summary

#### Scenario: analytics() aggregates the registry

- **WHEN** one delegation succeeded and one failed
- **THEN** `analytics()` MUST report `total == 2`, `active == 0`,
  `by_status == {"succeeded": 1, "failed": 1}`, and a non-null
  average duration

### Requirement: Automatic Sub-Role Routing

The system SHALL provide a `DelegationRouter`
(`delegation/router.py`) and a `DelegationSpawner.delegate_auto(task)`
method that routes the task over the parent role's available
`allowed_sub_roles` (declaration order) and delegates to the
selection. Deterministic classification SHALL score each candidate by
weighted token overlap between the task text and the role's
name/display name (weight 3), `preferred_tools` tokens (weight 2),
and description (weight 1), using exact or mutual-prefix (length ≥ 4)
token matching; ties resolve to candidate order and an all-zero score
SHALL raise `RoutingError` rather than guessing. Model-assisted
classification SHALL run ONLY when the persona's `models:` registry
declares an explicit `router` consumer binding (the `default` binding
MUST NOT enable it, and an injected test invoker alone MUST NOT
enable it); the production transport binds through `bind_langchain`
(CredentialProvider seam, budget-gated). ANY model-path failure —
resolution, denial, transport, or a reply naming no candidate — MUST
fall back to the deterministic score. `delegate_auto` SHALL raise
`ValueError` when no candidate sub-role is available.

#### Scenario: Deterministic routing picks the lexical best match

- **WHEN** `route("debug the code and fix the bugs", [writer, coder,
  researcher])` is awaited with no `router` binding
- **THEN** the decision MUST select `coder` with method
  `deterministic`

#### Scenario: Model path used only when the router binding exists

- **WHEN** the persona binds `router:` to a registry entry and the
  (mocked) model replies `researcher`
- **THEN** the decision MUST select `researcher` with method `model`
- **AND** with no `router` binding the same mocked invoker MUST NOT
  be called and the deterministic result MUST be returned

#### Scenario: Model failure or garbage reply falls back

- **WHEN** the bound model raises, or replies with text naming no
  candidate
- **THEN** the decision MUST equal the deterministic result

#### Scenario: Unroutable task raises instead of guessing

- **WHEN** every candidate scores zero for the task
- **THEN** `RoutingError` MUST be raised listing the scores
