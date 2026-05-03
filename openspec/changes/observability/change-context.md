# Change Context: observability

<!-- 3-phase incremental artifact:
     Phase 1 (pre-implementation): Req ID, Spec Source, Description, Contract Ref, Design Decision,
       Test(s) planned. Files Changed = "---". Evidence = "---".
     Phase 2 (implementation): Files Changed populated. Tests pass (GREEN).
     Phase 3 (validation): Evidence filled with "pass <SHA>", "fail <SHA>", or "deferred <reason>". -->

## Requirement Traceability Matrix

<!-- One row per SHALL/MUST requirement from specs/<capability>/spec.md.
     Req ID format: <capability>.<N> (sequential per capability).
     Phase 1: Fill Req ID, Spec Source, Description, Contract Ref, Design Decision, Test(s).
       Contract Ref: "---" — no machine-readable contracts apply (see contracts/README.md).
       Design Decision: D# from design.md that this requirement validates, or "---" if none.
       Files Changed and Evidence = "---".
     Phase 2: Fill Files Changed after implementation. Evidence still "---".
     Phase 3: Fill Evidence with "pass <SHA>", "fail <SHA>", or "deferred <reason>". -->

| Req ID | Spec Source | Description | Contract Ref | Design Decision | Files Changed | Test(s) | Evidence |
|--------|------------|-------------|-------------|----------------|---------------|---------|----------|
| observability.1 | specs/observability/spec.md:5-43 | Define `ObservabilityProvider` Protocol with 9 methods (lifecycle + 4 trace_* + start_span + flush/shutdown), `@runtime_checkable`, with enum validation for `tool_kind` and `op`. | --- | D7 | src/assistant/telemetry/providers/base.py, src/assistant/telemetry/providers/noop.py | 1.3, 1.4, 1.5 | pass bb5deec |
| observability.2 | specs/observability/spec.md:45-72 | Factory MUST return a functional `NoopProvider` under all three degradation levels (disabled, ImportError, runtime failure) with one-shot `assistant.telemetry` warning per process and never crash the app. | --- | D2 | src/assistant/telemetry/factory.py, src/assistant/telemetry/providers/langfuse.py | 1.11, 1.14 | pass bb5deec |
| observability.3 | specs/observability/spec.md:74-92 | `HarnessAdapter.invoke()` MUST emit exactly one `trace_llm_call` per invocation (after await) with model/persona/role/tokens/duration; on exception still emit with `metadata={"error": <type>}` then re-raise. | --- | D3 | src/assistant/telemetry/decorators.py, src/assistant/harnesses/sdk/deep_agents.py, src/assistant/harnesses/sdk/ms_agent_fw.py | 2.1, 2.3 | pass bb5deec |
| observability.4 | specs/observability/spec.md:94-107 | `DelegationSpawner.delegate()` MUST emit `trace_delegation` with parent_role, sub_role, task (sha256 hash if >256 chars), persona, duration_ms, outcome. | --- | D3 | src/assistant/telemetry/decorators.py, src/assistant/delegation/spawner.py | 2.4, 2.6 | pass bb5deec |
| observability.5 | specs/observability/spec.md:109-128 | Every extension `StructuredTool` and HTTP-builder tool MUST emit `trace_tool_call` with correct `tool_kind` ("extension" or "http"); errors recorded before re-raise. | --- | D3 | src/assistant/telemetry/tool_wrap.py, src/assistant/core/capabilities/tools.py, src/assistant/harnesses/sdk/deep_agents.py, src/assistant/http_tools/builder.py | 3.5, 3.6, 3.7, 3.8, 3.9 | pass bb5deec |
| observability.6 | specs/observability/spec.md:130-159 | Every `MemoryManager` public method MUST emit `trace_memory_op` with the fixed op enum; graphiti calls are NOT separately instrumented (single span at MemoryManager boundary). | --- | --- | src/assistant/telemetry/decorators.py, src/assistant/core/memory.py | 3.1, 3.2, 3.3 | pass bb5deec |
| observability.7 | specs/observability/spec.md:161-225 | `sanitize.py` MUST apply the 15-pattern ordered regex list to all string attrs/metadata/error messages, preserving known-safe semantic fields (persona, role, model, etc.) ONLY for scalar string values — list elements under safe keys MUST still be scrubbed (Iter 1 fix). | --- | D5 | src/assistant/telemetry/sanitize.py | 1.7, 1.8, sanitize-list-fix-iter1 | pass bb5deec |
| observability.8 | specs/observability/spec.md:216-229 | Register `atexit.register(provider.shutdown)` once; `LANGFUSE_FLUSH_MODE=per_op` causes every trace_* method to call `flush()` before returning; default mode is `shutdown`. | --- | D6 | src/assistant/telemetry/flush_hook.py, src/assistant/telemetry/factory.py, src/assistant/telemetry/providers/langfuse.py | 1.16, 1.17 | pass bb5deec |
| observability.9 | specs/observability/spec.md:231-244 | Default factory return SHALL be a `NoopProvider` whose Protocol methods are zero-allocation (advisory tracemalloc check: 3-run median within 4 KB tolerance over 10k iterations). | --- | D7 | src/assistant/telemetry/providers/noop.py | 1.5, 1.6 | pass bb5deec |
| observability.10 | specs/observability/spec.md:246-259 | `TelemetryConfig` frozen dataclass loaded via `_env()` helper pattern; missing or empty-string credentials yield `enabled=False`; empty-string case logs a distinguishing warning. | --- | D13 | src/assistant/telemetry/config.py | 1.1, 1.2 | pass bb5deec |
| observability.11 | specs/observability/spec.md:261-287 | `contextvars.ContextVar`-backed `set_assistant_ctx` / `get_assistant_ctx` / `assistant_ctx` context manager; survives across awaits; delegation pushes sub-role; concurrent delegations isolated via per-Task semantics. | --- | D4 | src/assistant/telemetry/context.py, src/assistant/cli.py, src/assistant/telemetry/decorators.py | 1.9, 1.10, 2.5, 2.7 | pass bb5deec |
| observability.12 | specs/observability/spec.md:289-299 | Telemetry module MUST NOT expose any inbound interface (no fastapi/flask/aiohttp.web/grpc server) and the package docstring SHALL declare "outbound-only". | --- | --- | src/assistant/telemetry/__init__.py | 5.2 | pass bb5deec |
| observability.13 | specs/observability/spec.md:301-308 | `flush_hook.py` and `docs/observability.md` MUST document the shutdown-mode delivery-loss tradeoff and the `LANGFUSE_FLUSH_MODE=per_op` opt-in (section titled "Delivery guarantees"). | --- | D6 | src/assistant/telemetry/flush_hook.py, docs/observability.md | 4.3 | pass bb5deec |
| harness-adapter.1 | specs/harness-adapter/spec.md:5-38 | Apply `@traced_harness` decorator to each concrete `SdkHarnessAdapter` subclass (DeepAgentsHarness, MSAgentFrameworkHarness stub) so each `invoke()` emits exactly one `trace_llm_call` after await; exception path still emits then re-raises. | --- | D3 | src/assistant/harnesses/sdk/deep_agents.py, src/assistant/harnesses/sdk/ms_agent_fw.py | 2.1, 2.2, 2.3 | pass bb5deec |
| delegation-spawner.1 | specs/delegation-spawner/spec.md:5-28 | Apply `@traced_delegation` to `DelegationSpawner.delegate` emitting parent/sub_role, persona, duration, outcome; task strings >256 chars MUST be replaced with `"sha256:<16-hex>"`; error path emits before propagating. | --- | D3 | src/assistant/delegation/spawner.py, src/assistant/telemetry/decorators.py | 2.4, 2.5, 2.6 | pass bb5deec |
| extension-registry.1 | specs/extension-registry/spec.md:5-28 | Wrap every `StructuredTool` from `Extension.as_langchain_tools()` at aggregation sites (not in extension code) so each invocation emits `trace_tool_call(tool_kind="extension", ...)`; metadata (name/description/args_schema) preserved. | --- | D3 | src/assistant/core/capabilities/tools.py, src/assistant/harnesses/sdk/deep_agents.py | 3.5, 3.6, 3.7 | pass bb5deec |
| capability-resolver.1 | specs/capability-resolver/spec.md:5-32 | Both extension-tool aggregation sites (`core/capabilities/tools.py` and `harnesses/sdk/deep_agents.py`) MUST call shared `wrap_extension_tools` helper from `telemetry/tool_wrap.py` — single source of truth, no inline closures. | --- | D3 | src/assistant/core/capabilities/tools.py, src/assistant/telemetry/tool_wrap.py | 3.6, 3.7 | pass bb5deec |
| http-tools.1 | specs/http-tools/spec.md:5-27 | Wrap HTTP tools inside `_build_structured_tool` (or successor) in `http_tools/builder.py` so each invocation emits `trace_tool_call(tool_kind="http", ...)`; sanitization applied to error messages (Bearer/Basic/Digest/Cookie). | --- | D3, D5 | src/assistant/http_tools/builder.py, src/assistant/telemetry/tool_wrap.py | 3.8, 3.9 | pass bb5deec |

## Design Decision Trace

<!-- One row per decision from design.md. Omit section entirely if no design.md exists. -->

| Decision | Rationale | Implementation | Why This Approach |
|----------|-----------|----------------|-------------------|
| D1: Singleton Provider Lifecycle | Reuse the Langfuse SDK client across calls so batching works; avoid threading a provider handle through every call site. | `src/assistant/telemetry/factory.py` | Per-call instances defeat SDK batching; explicit DI would churn every harness/extension/tool signature for no benefit. |
| D2: Three-Level Degradation State Machine | Telemetry must never crash the app under disabled / ImportError / runtime-init failure. | `src/assistant/telemetry/factory.py` (`_init_provider`) | Returning `Optional[Provider]` would force every call site into null-checks; raising would force boilerplate try/except everywhere. The noop pattern keeps consumers branch-free. |
| D3: Hook Integration via Decorators | One declarative insertion point per concern; refactoring the Protocol does not churn call sites. | `src/assistant/telemetry/decorators.py`, `src/assistant/telemetry/tool_wrap.py` | Explicit `provider.trace_*(...)` calls at every hook are easy to forget and hard to retrofit; a middleware chain is overkill for sync/async Python. |
| D4: Persona/Role Context Propagation via ContextVar | Spans need persona+role at emission, but hook sites (tool `_arun`, etc.) don't always receive them as args. | `src/assistant/telemetry/context.py` | Threading args through every signature is unviable; module-level globals break under async concurrency; `threading.local` doesn't cross `await`. ContextVar is task-local per PEP 567. |
| D5: Sanitization as a Pure Function at Emission | Centralize redaction so every provider applies the same ordered regex list to attrs/metadata. | `src/assistant/telemetry/sanitize.py` | Pure function is testable in isolation; emission-time application catches secrets regardless of which call-site originated them. Ordered regex (specific-before-generic) prevents `sk-lf-*` from being eaten by the generic `sk-*` matcher. |
| D6: Flush Mode via atexit | Reliable buffer drain on normal exit without breaking long-running processes. | `src/assistant/telemetry/flush_hook.py`, `src/assistant/telemetry/providers/langfuse.py` | `__del__` is unreliable under interpreter shutdown; context-manager-at-CLI breaks for future MCP/A2A servers with no exit boundary; atexit still fires for those. SIGKILL/OOM loss documented and addressable via `LANGFUSE_FLUSH_MODE=per_op`. |
| D7: NoopProvider is Zero-Allocation | The noop path is on the hot loop for every harness/tool/memory op; allocation here adds latency even when telemetry is off. | `src/assistant/telemetry/providers/noop.py` | A naive `pass`/dict-construction noop adds real overhead; explicit `return None` body with `**kwargs` accepts the unavoidable kwargs dict but allocates nothing further. Enum validation uses module-level frozensets. |
| D8: Test Strategy for 3-Level Degradation | Each degradation path needs a deterministic test; mirror the proven newsletter-aggregator pattern. | `tests/telemetry/test_langfuse_provider.py`, `tests/telemetry/test_factory.py` | Monkeypatching `builtins.__import__` simulates the missing-package case without removing the dep; same approach used elsewhere in the codebase, so the pattern is familiar. |
| D9: LANGFUSE_INIT_* Seeded in docker-compose | Local dev usable without UI signup; closes the gap newsletter-aggregator hit. | `docker-compose.langfuse.yml`, `docs/observability.md` | UI-signup-on-first-run forces every dev to repeat onboarding; committed `DUMMY-` prefixed values are gitleaks-friendly and visually flagged so they cannot accidentally reach prod. Startup sidecar refuses to launch with DUMMY values outside localhost. |
| D10: Claude Code Stop Hook Wiring (Documentation Only) | The repo-agnostic hook already exists in agentic-coding-tools; re-implementing duplicates code. | `docs/observability.md` | Re-implementing creates drift; documenting the wiring keeps the canonical implementation in one place. |
| D11: Test Fixtures for Singleton Reset and SpyProvider | Module-level singleton from D1 leaks between tests; ad-hoc patches are inconsistent. | `tests/telemetry/conftest.py` | Without an autouse reset fixture, test ordering invalidates level-2 ImportError tests. SpyProvider keeps the zero-allocation noop posture for unrecorded methods so it can stand in for the default provider. |
| D12: Optional Extra vs Dependency Group for Langfuse | Keep default install lean; let the deployment toggle decide whether to install the SDK. | `pyproject.toml` (`[project.optional-dependencies].telemetry`) | Dep groups (PEP 735) target workflows; observability is a deployment toggle. Optional extras have broader tooling compatibility today. Default deps would pull ~5 MB of Langfuse + transitive wheel data into every install. |
| D13: Empty-String Credentials Disambiguated From Unset | Empty creds are almost always misconfiguration; treating them as "intentional disable" hides bugs. | `src/assistant/telemetry/config.py` (`TelemetryConfig.from_env`) | Both cases produce `enabled=False`, but the empty-but-`LANGFUSE_ENABLED=true` case logs a distinguishing warning so users can debug. Whitespace normalized via `.strip()`. |

## Review Findings Summary

<!-- Parallel workflow only. Synthesized from artifacts/<package-id>/review-findings.json.
     Omit section for linear workflow. -->

| Finding ID | Package | Type | Criticality | Disposition | Resolution |
|------------|---------|------|-------------|-------------|------------|

## Coverage Summary

<!-- Populated during validation. Use exact counts. -->

- **Requirements traced**: 18/18
- **Tests mapped**: 18 requirements have at least one test
- **Evidence collected**: 18/18 requirements pass at HEAD bb5deec
- **Gaps identified**: None
- **Deferred items**: 9 low-priority polish findings deferred from IMPL_REVIEW rounds 2-3 (3 to v4 follow-up issue, 6 stylistic LOWs not blocking)
