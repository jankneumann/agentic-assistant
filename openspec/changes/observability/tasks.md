# Observability — Implementation Tasks

TDD-ordered: test tasks list before their implementation counterparts. Each implementation task declares a dependency on its corresponding test task.

Task IDs map to work-packages. Packages and their scopes are defined in `work-packages.yaml`.

## Phase 1 — Telemetry Module Foundation (wp-contracts)

- [ ] **1.1** Write tests for `TelemetryConfig.from_env()` and default values.
  **Spec scenarios**: observability — "Missing credentials default to disabled"
  **Design decisions**: D5 (config via `_env()` helper pattern)
  **Dependencies**: None

- [ ] **1.2** Implement `src/assistant/telemetry/config.py` — frozen `TelemetryConfig` dataclass, `from_env()` classmethod using `_env()` helper.
  **Dependencies**: 1.1

- [ ] **1.3** Write tests for the `ObservabilityProvider` Protocol: `isinstance` checks against noop and (stub) langfuse, tool_kind validation, required method presence.
  **Spec scenarios**: observability — "Noop implements the full Protocol surface", "Rejects mis-typed tool_kind"
  **Dependencies**: None

- [ ] **1.4** Implement `src/assistant/telemetry/providers/base.py` — `ObservabilityProvider` Protocol decorated with `@runtime_checkable`, including all 9 methods per spec.
  **Dependencies**: 1.3

- [ ] **1.5** Write tests for `NoopProvider` — protocol compliance, zero-allocation assertion via `tracemalloc`, protocol-level behavior under every first-class method.
  **Spec scenarios**: observability — "Noop implements the full Protocol surface", "Noop methods are zero-allocation", "Default configuration yields noop"
  **Design decisions**: D7 (zero-allocation noop)
  **Dependencies**: 1.4

- [ ] **1.6** Implement `src/assistant/telemetry/providers/noop.py` — `NoopProvider` with zero-allocation method bodies.
  **Dependencies**: 1.5

- [ ] **1.7** Write tests for `sanitize(value)` covering every pattern in the ordered regex list: the Langfuse-specific-before-generic-sk ordering invariant; persona-name and other known-safe-field passthrough; private submodule URL redaction; AWS access keys (`AKIA*`/`ASIA*`); GitHub PATs (`ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_`); Slack tokens (`xoxb-`/`xoxp-`/`xoxa-`); Google OAuth access tokens (`ya29.*`); database URLs with embedded credentials (postgres/mysql/mongodb/redis); `Authorization: Basic`, `Authorization: Digest`, and `Cookie:` header formats; `Bearer *` tokens; generic `key=value` catch-all.
  **Spec scenarios**: observability — "Langfuse-specific key is redacted before the generic secret-key pattern", "Common vendor-token formats are redacted", "Database URL with embedded credentials is redacted", "Private submodule URL is redacted", "Persona name is preserved"
  **Design decisions**: D5 (sanitization ordering)
  **Dependencies**: None

- [ ] **1.8** Implement `src/assistant/telemetry/sanitize.py` — ordered regex list, `sanitize(str) -> str`, `_sanitize_mapping(dict) -> dict`.
  **Dependencies**: 1.7

- [ ] **1.9** Write tests for the assistant context `ContextVar`: `set_assistant_ctx`/`get_assistant_ctx` round-trip; `assistant_ctx` context manager pushes on enter and pops on exit; **cross-await propagation** — a coroutine that awaits `asyncio.sleep(0)` sees the same context before and after the await; **delegation scope** — pushing a sub-role via `assistant_ctx(...)` during a simulated `delegate` call makes `get_assistant_ctx()` return the sub-role for spans emitted inside, then restores the parent context after exit.
  **Spec scenarios**: observability — "Context persists across await", "Delegation updates context for the sub-agent's spans"
  **Design decisions**: D4 (contextvars for persona/role propagation)
  **Dependencies**: None

- [ ] **1.10** Implement `src/assistant/telemetry/context.py` — `set_assistant_ctx`, `get_assistant_ctx`, `assistant_ctx` context manager.
  **Dependencies**: 1.9

- [ ] **1.11** Write tests for `LangfuseProvider` — lazy import behavior, 3-level graceful degradation (disabled, ImportError, runtime error), sanitization integration, flush mode switch.
  **Spec scenarios**: observability — "Langfuse implements the full Protocol surface", "Returns noop when langfuse package is missing", "Returns noop when provider init raises", "Shutdown mode batches events", "Per-op mode flushes each call"
  **Design decisions**: D2 (3-level state machine), D5 (sanitization at emission), D6 (flush via atexit)
  **Dependencies**: 1.4, 1.8

- [ ] **1.12** Add optional `telemetry` extra in `pyproject.toml` with `langfuse>=3.0,<4.0`.
  **Dependencies**: None

- [ ] **1.13** Implement `src/assistant/telemetry/providers/langfuse.py` — `LangfuseProvider` with lazy import (line ~107 pattern from newsletter), 3-level degradation handling, sanitization, per-op vs shutdown flush modes.
  **Dependencies**: 1.11, 1.12

- [ ] **1.14** Write tests for `factory.get_observability_provider()` — singleton caching across calls, atexit registration, 3-level degradation, one-warning-per-process behavior. Tests MUST include a pytest `autouse=True` fixture in `tests/telemetry/conftest.py` that resets the module-level `factory._provider = None` before each test, because the singleton otherwise leaks between test cases and breaks level-2 ImportError testing. Document the reset fixture as part of the test contract so downstream test files inherit it.
  **Spec scenarios**: observability — all three Graceful Degradation scenarios, "Default configuration yields noop"
  **Design decisions**: D1 (singleton lifecycle), D2 (3-level state machine), D6 (atexit registration), D11 (test fixture for singleton reset)
  **Dependencies**: 1.6, 1.13

- [ ] **1.15** Implement `src/assistant/telemetry/factory.py` — `get_observability_provider()` module-level singleton, `_init_provider()` state machine, atexit registration, one-shot warnings.
  **Dependencies**: 1.14

- [ ] **1.16** Write tests for `flush_hook` — atexit-path flush, `LANGFUSE_FLUSH_MODE=per_op` env switch, noop provider interaction.
  **Spec scenarios**: observability — "Shutdown mode batches events", "Per-op mode flushes each call"
  **Dependencies**: 1.15

- [ ] **1.17** Implement `src/assistant/telemetry/flush_hook.py` — atexit-registered shutdown, per-op opt-in wrapping.
  **Dependencies**: 1.16

- [ ] **1.18** Add module exports in `src/assistant/telemetry/__init__.py` — public re-exports: `get_observability_provider`, `ObservabilityProvider`, `set_assistant_ctx`, `get_assistant_ctx`.
  **Dependencies**: 1.15

## Phase 2 — Core Hooks: Harness + Delegation (wp-hooks)

- [ ] **2.1** Write tests for `@traced_harness` decorator — successful invoke emits trace_llm_call with correct kwargs, exception path emits trace before propagating, noop provider produces no side effects.
  **Spec scenarios**: harness-adapter — all three added scenarios
  **Design decisions**: D3 (decorator-based integration)
  **Dependencies**: 1.15

- [ ] **2.2** Implement `@traced_harness` in `src/assistant/telemetry/decorators.py`.
  **Dependencies**: 2.1

- [ ] **2.3** Apply `@traced_harness` to each **concrete** `SdkHarnessAdapter` subclass (decorator-at-base is dead code because subclasses override `invoke` entirely without `super()`). Apply to:
  - `DeepAgentsHarness.invoke` at `src/assistant/harnesses/sdk/deep_agents.py`
  - `MSAgentFrameworkHarness.invoke` stub at `src/assistant/harnesses/sdk/ms_agent_fw.py` (which raises `NotImplementedError` until the `ms-graph-extension` phase lands)
  Verify via test that the stub's trace emits exactly once with `metadata={"error": "NotImplementedError"}` before the exception propagates. The abstract base at `src/assistant/harnesses/base.py` (class `SdkHarnessAdapter`) does NOT need direct decoration.
  **Spec scenarios**: harness-adapter — "Deep Agents harness invocation is traced", "Harness exception still emits trace before propagating", "MSAgentFrameworkHarness stub is traced with the raised-exception path"
  **Dependencies**: 2.2

- [ ] **2.4** Write tests for `@traced_delegation` decorator — success path, error path (`outcome="error"`), long-task hashing.
  **Spec scenarios**: delegation-spawner — all three added scenarios
  **Design decisions**: D3 (decorator-based integration)
  **Dependencies**: 1.15

- [ ] **2.5** Implement `@traced_delegation` in `src/assistant/telemetry/decorators.py`, including the sub-role `assistant_ctx` push.
  **Dependencies**: 2.4

- [ ] **2.6** Apply `@traced_delegation` to `DelegationSpawner.delegate` in `src/assistant/delegation/spawner.py`.
  **Spec scenarios**: delegation-spawner — "Successful delegation emits trace_delegation", "Failed delegation emits trace with outcome=error"
  **Dependencies**: 2.5

- [ ] **2.7** Wire `set_assistant_ctx(persona, role)` at `src/assistant/cli.py` startup after persona+role are resolved.
  **Design decisions**: D4 (persona/role context propagation)
  **Dependencies**: 1.10

## Phase 3 — Knowledge + Tool Hooks (wp-hooks)

- [ ] **3.1** Write tests for `MemoryManager` tracing — each public method (`get_context`, `store_fact`, `store_interaction`, `store_episode`, `search`, `export_memory`) emits `trace_memory_op` exactly once with the correct `op` value from the set `{"context", "fact_write", "interaction_write", "episode_write", "search", "export"}`. Assert that calling `trace_memory_op(op="CONTEXT")` (wrong case) or any value outside the set raises `ValueError`. Use the `SpyProvider` fixture to capture calls.
  **Spec scenarios**: observability — "store_fact emits trace_memory_op with fact_write", "search emits trace_memory_op with search", "store_episode emits trace_memory_op covering the graphiti call", "Rejects mis-typed op value"
  **Dependencies**: 1.15

- [ ] **3.2** Instrument `src/assistant/core/memory.py` `MemoryManager` class by applying a `@traced_memory_op("<op>")` decorator to each of its 6 public methods (`get_context` → "context", `store_fact` → "fact_write", `store_interaction` → "interaction_write", `store_episode` → "episode_write", `search` → "search", `export_memory` → "export"). The `target` argument passed to `trace_memory_op` SHALL be the method's persona/key/query argument (hashed if over 256 chars per the shared convention).
  **Dependencies**: 3.1

- [ ] **3.3** Verify via integration test that `MemoryManager.store_episode()` (which internally invokes the graphiti client returned by `create_graphiti_client(persona)`) emits exactly ONE `trace_memory_op` with `op="episode_write"` at the MemoryManager boundary and NO second span from inside the graphiti client. This asserts the "no double-counting" design decision. Use the `SpyProvider` fixture; no changes to `src/assistant/core/graphiti.py` are required.
  **Spec scenarios**: observability — "store_episode emits trace_memory_op covering the graphiti call"
  **Dependencies**: 3.2

- [ ] **3.4** (No-op placeholder — reserved) Graphiti-layer tracing was intentionally omitted in favor of the `MemoryManager`-boundary-only approach (see design "Privacy Boundary Compliance" and the `MemoryManager Operation Tracing` Requirement). This task number is kept to avoid renumbering downstream references but has no implementation work. Close as "wontfix: superseded by tasks 3.1-3.3".
  **Dependencies**: 3.3

- [ ] **3.5** Write tests for `wrap_structured_tool()` — metadata passthrough, success path emits trace_tool_call, exception path emits trace before propagating.
  **Spec scenarios**: extension-registry — all three added scenarios
  **Dependencies**: 1.15

- [ ] **3.6** Implement `wrap_structured_tool(tool, tool_kind, ...)` in `src/assistant/telemetry/tool_wrap.py`.
  **Dependencies**: 3.5

- [ ] **3.7** Apply `wrap_structured_tool` at the extension tool aggregation sites. `Extension` is a Protocol (not a subclass-able base), so wrapping happens at the **call sites** that iterate `ext.as_langchain_tools()`:
  - `src/assistant/core/capabilities/tools.py` line ~41 — capability-resolver aggregation
  - `src/assistant/harnesses/sdk/deep_agents.py` line ~27 — harness tool bundle
  Both sites apply `[wrap_structured_tool(t, tool_kind="extension", ...) for t in ext.as_langchain_tools()]`. Factor out a shared helper `wrap_extension_tools(ext)` in `src/assistant/telemetry/tool_wrap.py` so both sites call the same function.
  **Spec scenarios**: extension-registry — "Extension tool invocation emits trace_tool_call", "Tool metadata passthrough is preserved"; capability-resolver — "Aggregated extension tools are traced"
  **Dependencies**: 3.6

- [ ] **3.8** Write tests for HTTP tool wrapping — builder-constructed tools emit trace with `tool_kind="http"`, Authorization header sanitization in error paths.
  **Spec scenarios**: http-tools — all three added scenarios
  **Dependencies**: 1.15, 1.8

- [ ] **3.9** Apply `wrap_structured_tool` inside `_build_tool` (line ~186) in `src/assistant/http_tools/builder.py` so every returned `StructuredTool` is wrapped with `tool_kind="http"` before it is returned to the caller.
  **Dependencies**: 3.8

## Phase 4 — Dev Infrastructure (wp-devops)

- [ ] **4.1** Write tests for `docker-compose.langfuse.yml` validity — compose file parses, all services have required env vars, `LANGFUSE_INIT_*` vars present.
  **Design decisions**: D9 (LANGFUSE_INIT_* from day 1)
  **Dependencies**: None

- [ ] **4.2** Create `docker-compose.langfuse.yml` at repo root — Postgres 17 + ClickHouse + Redis + MinIO + langfuse-web:3100 + langfuse-worker, with committed dev-default `LANGFUSE_INIT_*` values.
  **Dependencies**: 4.1

- [ ] **4.3** Write `docs/observability.md` including these required sections: Quickstart (docker-compose up, env vars, run assistant); **Delivery guarantees** (shutdown-mode tradeoff, `LANGFUSE_FLUSH_MODE=per_op` opt-in); Privacy and sanitization notes; Dev-only credential warning (and the `DUMMY-` prefix convention); CI/CD considerations (why the `langfuse-smoke` job is opt-in); Claude Code Stop hook wiring instructions (pointer to `agent-coordinator/scripts/langfuse_hook.py`); Minimum requirements (Python 3.12, Langfuse v3.x).
  **Spec scenarios**: observability — "Shutdown-mode delivery loss is documented"
  **Design decisions**: D6 (shutdown-mode tradeoff), D9 (dev credentials + DUMMY prefix), D10 (documentation-only Stop hook), D12 (optional extra rationale)
  **Dependencies**: 4.2

- [ ] **4.4** Update `README.md` — add a brief "Observability" section linking to `docs/observability.md`.
  **Dependencies**: 4.3

## Phase 5 — Integration & Validation (wp-integration)

- [ ] **5.1** Write integration test `tests/telemetry/test_cli_span_emission.py` — run `assistant -p <fixture-persona>` REPL startup, assert that harness/delegation/memory calls during a scripted interaction emit the expected spans through a noop-provider spy.
  **Spec scenarios**: observability — spans emit on each hook, with correct persona/role attribution
  **Dependencies**: 2.3, 2.6, 3.2, 3.4, 3.7, 3.9

- [ ] **5.2** Write integration test `tests/telemetry/test_privacy_compliance.py` — exercise the telemetry module under the privacy-guard plugin fixtures; assert no filesystem I/O is attempted by any provider path; additionally assert the `No Inbound Interfaces` constraint by importing the entire `src.assistant.telemetry` package tree and verifying that `fastapi`, `flask`, `aiohttp.web`, and `grpc.aio.server` do NOT appear in `sys.modules` after the import; finally assert that `src/assistant/telemetry/__init__.py`'s module docstring contains the phrase `outbound-only`.
  **Spec scenarios**: observability — "Module docstring declares outbound-only posture"
  **Design decisions**: Privacy Boundary Compliance, D1 (singleton)
  **Dependencies**: 1.15, 1.18

- [ ] **5.3** Write tests asserting the `FIXTURE_PERSONA_SENTINEL_v1` sentinel is NOT present in any emitted span attribute when the fixture persona is active.
  **Dependencies**: 2.3, 5.1

- [ ] **5.4** Run full quality gates: `uv run pytest tests/`, `uv run ruff check src tests`, `uv run mypy src tests`, `openspec validate observability --strict`.
  **Dependencies**: all prior tasks

- [ ] **5.5** **[OPTIONAL — advisory, not blocking merge]** Add a CI smoke test that spins up Langfuse via `docker-compose.langfuse.yml`, runs a scripted assistant interaction with `LANGFUSE_ENABLED=true`, and asserts spans land in Langfuse via the admin API. Because the Langfuse stack (Postgres + ClickHouse + Redis + MinIO + web + worker) exceeds typical GH Actions runner capacity (~4GB RAM, often OOMs on ClickHouse), this task is **optional**: if included, it MUST run only under a `langfuse-smoke` job guarded by a repository variable `RUN_LANGFUSE_SMOKE=true`, or be attached to a self-hosted runner tagged `large`. The default CI path uses the noop provider spy (task 5.1) and does NOT require live Langfuse.
  **Dependencies**: 4.2, 5.4
