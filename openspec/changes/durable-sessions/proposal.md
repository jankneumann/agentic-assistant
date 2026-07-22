# durable-sessions — Sessions, Approvals, Ledger, Audit on the Persona DB (P30)

## Why

P30 is the cross-phase deferral consolidation: five separately-recorded
deferrals all block on the same missing substrate — durable state on
the persona DB.

1. **Conversations die with the process.** The DeepAgents harness pins
   every agent to a fresh `InMemorySaver`; the harness-adapter spec's
   Durable Session Persistence requirement (written by
   capability-protocols-v2) has been contract-only since P24.
2. **Serving surfaces reject known contextIds.** The in-memory
   `SessionRegistry` (living in `assistant.a2a.task_handler`, reused by
   MCP — the recorded P17 D7 relocation follow-up) treats every
   expired/restart-lost `thread_id` as unknown.
3. **`require_confirmation` means deny.** Since P13, every guardrail
   confirmation request is refused at the model binding, the P26
   clean-room gateway, and the P28 learning-apply gate — the
   guardrail-provider ApprovalRequest interrupt/resume contract (P24)
   has no implementation.
4. **Budget ledgers are process- or host-local.** The P13 BudgetLedger
   protocol explicitly deferred the persona-DB backend.
5. **No durable audit trail.** P25/P28 audit records exist only as
   telemetry spans; the durable decision log was deferred with the
   approval flow.

## What Changes

- **Persona `sessions:` section** (`core/durable.py`,
  `parse_sessions_config`, validated at load): `durable: true` +
  optional `session_ttl_seconds` / `approval_ttl_seconds`. **No
  section = every in-memory default unchanged** (clean-room posture).
  `durable: true` without a resolvable `database_url` fails
  actionably wherever the durable tier is built — declared durability
  never silently degrades.
- **Durable checkpointer** (NEW DEPENDENCY
  `langgraph-checkpoint-postgres`, roadmap-sanctioned):
  `DeepAgentsHarness` accepts an injectable `checkpointer` (and an
  explicit `thread_id` for re-binding); un-injected harnesses resolve
  via `harnesses/sdk/checkpointer.py` — `InMemorySaver` by default, a
  process-cached `AsyncPostgresSaver` for durable personas. The
  saver's own `setup()` runs once per process/url; its schema is
  package-owned and deliberately NOT alembic-managed (documented).
- **SessionRegistry extraction + durable re-bind**: the registry moves
  to the neutral `assistant/harnesses/sessions.py` (compat re-exports
  stay in `a2a.task_handler`); it gains an optional session-metadata
  store + `rebind_factory`, and an async `resolve(thread_id)` —
  live session → durable re-bind (checkpointer restores state) →
  reject only truly unknown/expired. A2A and MCP unknown-contextId
  handling flows through `resolve`; `sessions` table rows
  (thread_id/persona/role/harness/timestamps/expires_at/status) land
  via alembic migration **002**.
- **Approval interrupt/resume** (`core/capabilities/approvals.py`):
  `ApprovalRequest` (MCP-elicitation-shaped per the P24 spec) +
  `ApprovalStore` (sync protocol; Postgres implementation in
  `core/durable.py`, in-memory twin for tests/fakes). Where a durable
  store exists, `require_confirmation` SUSPENDS instead of denying:
  `consume_or_suspend` consults resolved approvals first (approve =
  consumed exactly once → proceed; human deny = `ApprovalDeniedError`,
  consumed), reuses an existing pending request, else persists a new
  one and raises the typed `PendingApprovalError`. Serving surfaces:
  A2A maps it to a REAL non-terminal `input-required` task state (no
  `failed` update); AG-UI surfaces the class name on its
  `RunErrorEvent` (D8 redaction preserved); the CLI prints resume
  instructions. Resume is retry-shaped v1: `assistant approvals
  list/approve/deny` records the decision (idempotent,
  identity-stamped, audited), the caller retries. The P28
  learning-apply gate and P26 clean-room gateway flow through the
  same helper; **without durable sessions every site keeps its P13
  deny fallback**.
- **PostgresBudgetLedger**: `guardrails.budgets.model_call.persist:
  db` selects the persona-DB spend ledger (`guardrail_spend` table,
  same migration); `memory`/`file` unchanged.
- **Durable audit trail**: `audit_log` table (same migration);
  `emit_guardrail_audit` additionally appends identity-carrying
  decisions to the persona's registered durable sink, and approval
  decisions append `approval.decision` records. Telemetry spans are
  unchanged and continue regardless.

## Impact

- Affected specs: `harness-adapter` (durable requirements
  implemented), `guardrail-provider` (interrupt/resume replaces
  deny-until-interrupt where durable; `persist: db`), `a2a-server`
  (real input-required + re-binding), `mcp-server` (durable re-bind),
  `cli-interface` (approvals commands), `learning` (apply approval
  path), NEW capability `durable-sessions` (config + store tier).
- Affected code: `core/durable.py` (new), `core/capabilities/
  approvals.py` (new), `harnesses/sessions.py` (new),
  `harnesses/sdk/checkpointer.py` (new), `core/db.py` (sync engine
  tier), `core/capabilities/{guardrails,audit,model_bindings}.py`,
  `core/{persona,cleanroom,learning}.py`, `harnesses/sdk/
  {deep_agents,ms_agent_fw}.py`, `a2a/{task_handler,server}.py`,
  `mcp/server.py`, `transports/a2a/mapper.py`, `web/app.py`,
  `cli.py`, `migrations/versions/002_durable_sessions.py`,
  `personas/_template/persona.yaml`, `pyproject.toml`.
- **No live Postgres in dev/CI**: all DB behavior is tested against
  sqlite engines (same store code, `metadata.create_all`) and
  in-memory twins; checkpointer construction is faked. Migration 002
  runs against a real persona DB via `assistant db upgrade`.
- Deferred (recorded): true mid-run interrupt/resume from the
  LangGraph checkpoint (v1 resume is retry-shaped — the retried
  operation consults resolved approvals); email/messaging approval
  channels (P29 channel adapters); MSAF durable conversation
  persistence (no agent-framework checkpointer injection point);
  escalation-with-justification submission surface; A2A multi-turn
  task continuation (`message/send` with `taskId`).
