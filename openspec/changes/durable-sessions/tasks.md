# durable-sessions — Tasks

## 1. Substrate

- [x] 1.1 Pin `langgraph-checkpoint-postgres` (roadmap-sanctioned new
      dependency); `uv lock` + full-suite baseline green
- [x] 1.2 `core/db.py`: sync engine tier (`sync_db_url` normalization
      to `postgresql+psycopg`, `create_sync_engine` cache + test hook)
- [x] 1.3 `core/durable.py`: `SessionsConfig` + `parse_sessions_config`
      (actionable errors; falsy default), SQLAlchemy Core schema
      (`sessions`, `approvals`, `guardrail_spend`, `audit_log`)
- [x] 1.4 Wire `sessions:` into `PersonaConfig` + `PersonaRegistry.load`
      + annotated section in `personas/_template/persona.yaml`
- [x] 1.5 Alembic migration `002_durable_sessions` (JSONB/timestamptz;
      header documents the checkpointer-schema separation)

## 2. Durable checkpointer (DeepAgents)

- [x] 2.1 `harnesses/sdk/checkpointer.py`: `resolve_checkpointer`
      (InMemorySaver default; process-cached `AsyncPostgresSaver` via
      `from_conn_string` + one-time `setup()`; conn-string driver
      strip; `close_checkpointers` + test hook)
- [x] 2.2 `DeepAgentsHarness`: injectable `checkpointer` +
      `approval_store` + explicit `thread_id` kwargs; `create_agent`
      resolves the checkpointer; `spawn_sub_agent` propagates the
      injected seams
- [x] 2.3 `MSAgentFrameworkHarness`: `thread_id` + `approval_store`
      injection parity (durable conversation persistence recorded as
      deferred — no SDK checkpointer seam)

## 3. Session registry extraction + durable re-bind

- [x] 3.1 Move `Session`/`SessionRegistry`/`SessionFactory` to
      `harnesses/sessions.py`; compat re-exports in
      `a2a.task_handler`; A2A/MCP suites stay green
- [x] 3.2 Registry durable tier: metadata store record/touch,
      `rebind_factory`, async `resolve()` (live → re-bind → reject),
      durable TTL lapse, role scoping, best-effort store I/O
- [x] 3.3 `core/durable.py`: `PostgresSessionStore` +
      `InMemorySessionStore`; `durable_stores_for(persona)` resolution
      + audit-sink registration + `_clear_durable_state`
- [x] 3.4 A2A: `_resolve_session` via `resolve()`; `build_a2a_state`
      store/rebind/role/harness kwargs. MCP: `_ask` via `resolve()`;
      `build_mcp_state` per-role rebind partials. `web/app.py`
      lifespan wires stores + rebind factories
      (`create_harness(..., thread_id=...)`) for durable personas

## 4. Approval interrupt/resume

- [x] 4.1 `core/capabilities/approvals.py`: `ApprovalRequest`
      (elicitation-shaped, default approve/deny schema), typed errors
      (`PendingApprovalError`, `ApprovalDeniedError`,
      `ApprovalAlreadyDecidedError`, `UnknownApprovalError`),
      `ApprovalStore` protocol, `InMemoryApprovalStore`,
      `build_approval_request`, `consume_or_suspend`
- [x] 4.2 `core/durable.py`: `PostgresApprovalStore` (lazy pending
      expiry, first-decision-wins, consume-once; identity round-trip)
- [x] 4.3 `check_model_call`: suspend-with-store / deny-fallback split;
      `bind_langchain` / `bind_msaf_chat_client` /
      `OpenAICompatibleClient` pass-through; both harness
      `_build_model` paths resolve the store and treat
      Pending/Denied as policy stops
- [x] 4.4 P26 clean-room gateway + P28 learning apply: `approvals`
      kwarg through `_check_gateway_action` / `_check_apply_action`
      (suspend when durable, P13 deny fallback otherwise); CLI passes
      the persona's store
- [x] 4.5 Serving surfaces: A2A mapper `PENDING_APPROVAL_ERROR_CLASSES`
      → final non-terminal `input-required` (no failed); deny-fallback
      mapping unchanged; CLI REPL prints suspend/deny guidance
- [x] 4.6 CLI `assistant approvals list/approve/deny` (idempotent
      decisions, `approval.decision` span + durable audit row,
      actionable errors without durable sessions)

## 5. Budget ledger + audit

- [x] 5.1 `persist: db` parse (`spend_persist` on `GuardrailConfig`);
      `budget_ledger_for(..., database_url=...)` selects
      `PostgresBudgetLedger` (no url = actionable error);
      `PolicyGuardrails(database_url=...)` threaded from the resolver
      and `select_guardrails`
- [x] 5.2 `core/durable.py`: `PostgresBudgetLedger` (persona-scoped
      record/spent_since)
- [x] 5.3 Durable audit: `PostgresAuditStore`/`InMemoryAuditStore`,
      sink registry + `record_durable_audit`; `emit_guardrail_audit`
      appends identity-carrying decisions best-effort

## 6. Tests + docs

- [x] 6.1 `tests/core/capabilities/test_approvals.py` — request shape,
      store lifecycle, consume_or_suspend, check_model_call split
- [x] 6.2 `tests/core/test_durable_sessions.py` — config parse +
      persona load, sqlite-backed stores (sessions/approvals/spend/
      audit), `persist: db` selection, `durable_stores_for`, audit
      sink behavior
- [x] 6.3 `tests/harnesses/test_checkpointer.py` +
      `test_session_rebind.py` — injection, resolution, re-bind,
      expiry, role scoping, A2A handler re-bind end-to-end
- [x] 6.4 `tests/transports/a2a/test_mapper_pending_approval.py` —
      non-terminal input-required vs deny fallback
- [x] 6.5 `tests/test_approval_gates.py` — clean-room + learning
      suspend/resume/deny-fallback; `tests/cli/test_approvals_cli.py`
- [x] 6.6 CLAUDE.md updates (all deny-until-interrupt mentions),
      template persona.yaml annotations
- [x] 6.7 Gates: `uv run pytest tests/ -q`, `ruff check src tests`,
      `mypy src tests`, `openspec validate durable-sessions --strict`
