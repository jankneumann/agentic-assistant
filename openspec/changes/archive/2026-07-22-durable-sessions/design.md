# durable-sessions — Design

## D1. One persona flag gates the whole tier

`sessions: {durable: true}` switches on, together: the Postgres
checkpointer, the session-metadata store, the approval interrupt flow,
and the durable audit log. Rationale: these are one substrate (the
persona DB) and partial enablement creates incoherent states (e.g.
approvals that suspend runs nobody can resume because conversations
are not durable). `persist: db` for the budget ledger stays a separate
guardrails knob because budgets are meaningful without durable
sessions and predate this phase.

Falsy default = byte-identical pre-P30 behavior. Declared-but-
unbuildable (`durable: true`, no `database_url`) raises actionably at
tier-construction time (checkpointer resolution, `durable_stores_for`,
CLI) — the P20 fail-closed posture, mirroring declared A2A auth. The
url is resolved through the credential seam at persona load, so parse
time cannot validate it.

## D2. Adopt the LangGraph checkpointer; do not invent a session store

Per the harness-adapter requirement: conversation STATE lives in the
checkpointer (`langgraph-checkpoint-postgres`, `AsyncPostgresSaver`),
keyed by `thread_id`. The `sessions` table stores only METADATA
(ownership, validity): "is this thread known, whose is it, is it still
valid?" — the two answer different questions and are owned by
different code (package `setup()` vs alembic 002). One process-cached
saver per database url; `create_agent` awaits
`resolve_checkpointer(persona)` when nothing is injected, so tests
inject fakes and the InMemorySaver default is preserved exactly.

**Alembic vs `setup()`**: the checkpointer schema belongs to
langgraph-checkpoint-postgres and versions with it — wrapping it in
our migrations would fork its upgrade path. Migration 002 owns only
the four assistant tables (`sessions`, `approvals`, `guardrail_spend`,
`audit_log`). Documented in `core/durable.py`, the migration header,
and the template persona.yaml.

## D3. Registry extraction to `harnesses/sessions.py`

The recorded P17 D7 relocation: MCP importing session machinery from
`assistant.a2a.task_handler` was an inverted dependency. The harness
layer is the natural neutral home (the registry manages harness
instances; both serving surfaces already import harness modules).
`a2a.task_handler` re-exports `Session`/`SessionRegistry`/
`SessionFactory`/`DEFAULT_IDLE_TTL_SECONDS` so existing imports and
tests stay green.

`resolve(thread_id)` is ADDITIVE and async (re-binding awaits the
factory); `lookup` stays sync and unchanged for pre-P30 callers.
Re-bind constructs a harness with the SAME `thread_id`
(`create_harness(..., thread_id=...)` — both SDK harness constructors
gained the kwarg) and re-registers the session; a rebind factory that
produces a mismatched thread_id is a programming error and raises.
Role scoping: a durable row whose `role` differs from the resolving
registry's role is treated as unknown (never silently continue a
conversation under another role). Store I/O around create/lookup is
best-effort (WARNING, never breaks serving); resolve degrades to
"unknown" on store failure.

In-process idle expiry keeps releasing resources only. Durable
validity is a separate `session_ttl_seconds` window stamped on the
metadata row (0 = never lapses), slid on touch; a lapsed row is marked
`expired` and rejected.

## D4. Approvals: sync store, retry-shaped resume

The three confirmation sites (`check_model_call`, the clean-room
gateway check, the learning apply check) are synchronous functions, so
`ApprovalStore` is a sync protocol (exactly like the P13
`BudgetLedger`) over the new sync engine tier
(`core/db.py::create_sync_engine`, urls normalized to
`postgresql+psycopg` — psycopg v3 arrives with the checkpointer
dependency). Short queries; acceptable from async contexts.

**Resume semantics (v1, retry-shaped).** True mid-run resume — waking
the exact suspended LangGraph run from its checkpoint — needs
interrupt plumbing through deepagents that does not exist yet. v1
implements the spec's observable contract without it:
`consume_or_suspend` first CONSULTS resolved approvals for
(persona, action_type, resource) — an approve decision is consumed
exactly once and the action proceeds; a human deny surfaces as
`ApprovalDeniedError` (also consumed, so a later attempt re-files); a
live pending request is re-raised with the SAME id (no duplicates on
retry); otherwise a new request is persisted and
`PendingApprovalError` carries its id. Because requests and decisions
are DB rows, the round-trip survives restarts — the durable-session
scenario "suspend survives a restart" holds with the retried
operation as the resume vehicle. Recorded follow-up: checkpoint-level
interrupt/resume once the harness SDK exposes it.

**Matching on (persona, action_type, resource)** rather than a token
bound to one run: the retry is typically a NEW run (fresh
`_build_model` walk), so run-scoped tokens could never match. The
window in which a different run of the same persona could consume an
approval for the same action+resource is accepted and documented —
the approved THING is the action on the resource, which is what the
human saw in the request message.

## D5. Serving-surface mapping

- **A2A**: new `PENDING_APPROVAL_ERROR_CLASSES` (leaf class names) in
  the mapper. `PendingApprovalError` → ONE `status-update` with
  `state=input-required`, `final=true` (stream-final; the TASK is
  non-terminal awaiting input) and NO `failed` update. The P13
  fallback classes (`ModelCallDeniedError`) keep the observational
  input-required → failed sequence — personas without durable
  sessions still deny.
- **AG-UI**: the existing `RunErrorEvent(code=<class>)` carries
  `PendingApprovalError` — the D8 class-name-only redaction rule
  forbids richer payloads on this surface, and the trimmed AG-UI
  vocabulary has no CUSTOM event; the approval id is discoverable via
  `assistant approvals list`. A dedicated approval event type is
  deferred with the AG-UI vocabulary expansion.
- **CLI/REPL**: `PendingApprovalError` prints resume instructions
  (REPL stays alive; retry the turn after deciding);
  `ApprovalDeniedError` prints the denial.

## D6. Audit: same spans, plus a durable sink

`emit_guardrail_audit` keeps its exact span behavior (identity-only,
defensive) and additionally appends to a per-persona registered sink
(`core/durable.py` registry, populated when `durable_stores_for`
builds the tier; tests register in-memory sinks). Approval decisions
append `approval.decision` rows + an `approval.decision` span (escape
hatch, P25 precedent). No sink registered → no-op; append failures
warn and never change enforcement.

## D7. Testing without Postgres

Store implementations are SQLAlchemy Core against the shared
`durable.metadata`; tests run them on sqlite (`metadata.create_all`,
StaticPool) — real SQL, no server, public suite stays DB-free in the
ADR-0004 sense. The in-memory twins (`InMemoryApprovalStore`,
`InMemorySessionStore`, `InMemoryAuditStore`) are semantics twins used
where a store object is injected (registry/CLI/gate tests).
Checkpointer tests patch `_build_durable_saver` /
`resolve_checkpointer`; no `AsyncPostgresSaver` is ever constructed in
tests. Migration 002 mirrors `durable.metadata` with JSONB/timestamptz
and is exercised only against a real persona DB via `assistant db
upgrade` (documented; no opt-in integration test added because no
Postgres exists in this environment).

## D8. MSAF parity

`MSAgentFrameworkHarness` gains the same `thread_id` +
`approval_store` injection seams (session-registry re-bind and the
approval flow work identically), but durable CONVERSATION persistence
for MSAF is deferred — agent-framework 1.10 exposes no checkpointer
injection point (same posture as the P21 mid-turn retrieval
deferral, recorded in the harness docstring).

## D-review addendum (owner review 2026-07-19) — schema ownership vs operator alignment

Question raised: why not fold the checkpointer schema into alembic for
alignment/idempotency? Resolution kept as designed — the checkpointer
tables are langgraph-checkpoint-postgres's private, versioned storage
format with its OWN migration system (`checkpoint_migrations`);
copying its DDL into alembic guarantees drift on library upgrade and
couples us to private internals. Idempotency is preserved (both
owners are idempotent). The legitimate gap was operator experience:
schema materialized on first use, not at provision time. Amendment:
`assistant db upgrade -p <persona>` now also runs the checkpointer
`setup()` for durable personas — one operator command, two schema
owners. Flip condition recorded: if checkpoint data is ever treated
as ours (relational queries, added indexes/columns, retention), the
schema moves into alembic as a deliberate ownership transfer.
