# delegation-context — Design

## D1: DelegationContext builds ON the P25 identity, never duplicates it

`AgentIdentity.delegation_chain` (P25) already carries role ancestry.
`DelegationContext` therefore carries the CHILD `AgentIdentity` for
the hop and exposes no chain field of its own — the chain is read
from `identity.delegation_chain` / `chain_display()`. A public test
asserts the dataclass has no `delegation_chain` attribute.

## D2: Prompt injection mirrors D27, block leads the prompt

The rendered `## Delegation context` block is prepended by the
SUB-harness's prompt composition (`_compose_system_prompt` /
`_compose_instructions`) ahead of the D27 `## Recent context` section
— the sub-agent reads who delegated and under what bounds before its
memory. Injection point is a `delegation_context` constructor kwarg
on both SDK harnesses (set only by `spawn_sub_agent`), keeping the
non-delegated path byte-identical to pre-P12 output.

Known overlap, accepted: the context block's `memory_snippets`
(fetched under the sub-role by the spawner, limit 5) can overlap the
sub-harness's own D27 retrieval (limit 10). Both are bounded; the
context block is the harness-agnostic carrier for adapters without
D27 retrieval. Deduplication is deferred until it hurts.

## D3: Additive spawn_sub_agent contract + signature-inspection fallback

`spawn_sub_agent(role, task, tools, extensions, context=None)` — the
default preserves the old behavior. The spawner inspects the target's
signature and calls the pre-P12 shape (context dropped, WARNING
logged) when the adapter predates the keyword, so out-of-tree
adapters and old test doubles keep working without a shim.

## D4: Cycle detection is a structural check, before depth + policy

Cycle = `sub_role == identity.role` (self-delegation) or
`sub_role in identity.delegation_chain`. Checked after the ACL /
availability `ValueError`s and BEFORE the P25 depth ceiling and the
`check_delegation` guardrail — a cycle is structurally wrong
regardless of ceilings or policy — and emits the same audit record as
a depth denial. Opt-out is per parent role:
`delegation.allow_recursive: true` (off by default), consistent with
the other `delegation:` knobs (`allowed_sub_roles`, `max_concurrent`).
The P25 `max_chain_depth` ceiling still bounds recursion when
`allow_recursive` is enabled.

## D5: delegate_parallel queues under a semaphore instead of tripping the ceiling

`delegate()` keeps its hard `max_concurrent` RuntimeError (spec'd
behavior for direct calls). `delegate_parallel` wraps each pair in a
semaphore sized to the parent role's `max_concurrent` (optionally
narrowed by the `max_concurrent` argument) so excess tasks WAIT; the
in-flight counter can therefore never exceed the ceiling. Results
come back via `asyncio.gather(return_exceptions=True)` mapped to
`DelegationOutcome` markers in input order — per-task isolation, no
fail-fast.

## D6: Monitoring registry lives on the spawner; cancellation via asyncio

Every `delegate()` call registers a `DelegationRecord` and (when
running inside a task) its `asyncio.Task`. `cancel(id)` cancels that
task — the awaiting caller sees `CancelledError`; `delegate_parallel`
maps it to a `cancelled` outcome. Finished records are retained
(bounded at 256, oldest evicted) for `analytics()`. `deadline_seconds`
is both a constraint communicated to the sub-agent AND enforced by
the spawner via `asyncio.timeout` (a deadline nobody enforces is a
suggestion).

## D7: Analytics without new tables (DEVIATION from old roadmap text)

The roadmap row said "delegation analytics tables". Recorded
deviation: no new DB tables and no migration in this phase. Rationale:
(a) `trace_delegation` (P4) already emits a durable, queryable span
per delegation with outcome + duration; (b) personas with a DB get a
one-line `[delegation] parent -> sub: task` summary via the existing
`record_interaction` path (interactions table), distinguishable from
the sub-agent's own post-turn capture and a no-op for file-backed
memory; (c) the in-process registry answers live "what is running /
what happened this session" queries. A dedicated table adds a
migration + a second write path for data telemetry already carries.
If a future phase needs cross-session relational analytics, that is
a persona-DB ledger concern (same bucket as the deferred budget
ledger).

## D8: Router is deterministic-first; model assist is binding-gated

Scoring: task tokens (lowercase alphanumerics, len ≥ 3, minus a small
stopword list) matched against role name/display-name (weight 3),
`preferred_tools` source+operation tokens (weight 2), and description
tokens (weight 1). Token match is exact OR mutual-prefix for len ≥ 4
("draft"/"drafting", "write"/"writer") — a cheap stemmer substitute.
Ties resolve to candidate order (the parent's `allowed_sub_roles`
declaration order); an all-zero score raises `RoutingError` rather
than guessing (delegating a research task to a writer at random is
worse than asking the caller to name the role).

Model-assisted classification runs ONLY when the persona declares an
explicit `router` consumer binding (the `default` binding never
enables it — same opt-in posture as the P20 `embeddings` binding).
The default invoker resolves `ModelRequest(consumer="router")`
through `RegistryModelProvider` and binds via `bind_langchain`, so
credentials stay on the CredentialProvider seam and every call is
budget-gated. ANY failure — resolution, guardrail/budget denial,
transport, or a reply naming no candidate — falls back to the
deterministic score with a WARNING: the router must never make
delegation less available than it was before P12. (Deviation note: a
budget denial is treated as a fallback trigger rather than a policy
stop, because the deterministic path spends nothing — the denial
denies the MODEL CALL, not the delegation.)

`model_invoker` is an injectable async transport for tests; injecting
it does NOT enable the model path (the binding is the only gate — a
public test proves the invoker is not called when unbound).

## D9: Spawner memory access is lazy and error-swallowed

The spawner accepts an optional `memory_policy`; otherwise it lazily
resolves the persona's policy via `CapabilityResolver` once. Snippet
fetch and outcome capture are error-swallowed — context enrichment
and analytics must never fail a delegation that would previously have
succeeded.

## D10: traced_delegation span vocabulary unchanged

The decorator now passes the new keyword arguments through; the
emitted span still carries only (parent_role, sub_role, task-with-
256-char-hash-rule, persona, duration_ms, outcome) — no new trace op,
matching the P25 "no new trace op" precedent.

## Out of scope / deferred

- CLI surface for `delegate_auto` / `delegate_parallel` / `cancel`
  (the REPL keeps `/delegate <role> <task>`; new commands land with
  the next CLI pass).
- Durable delegation records (persona-DB ledger) and cross-session
  analytics.
- MSAF mid-turn context updates (blocked on the same SDK injection
  point as D27 mid-turn retrieval).
- Model-assisted routing for MSAF-dialect-only personas (router uses
  the LangChain binding; deterministic path is dialect-independent).
