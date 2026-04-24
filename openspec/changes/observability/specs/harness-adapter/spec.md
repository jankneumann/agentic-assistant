# harness-adapter Specification Delta

## ADDED Requirements

### Requirement: Harness Invocation Emits Observability Span

The system SHALL emit exactly one `trace_llm_call` observability span per invocation of any `SdkHarnessAdapter.invoke(...)` implementation. A `@traced_harness` decorator SHALL record the start time, await the underlying call, and then invoke `get_observability_provider().trace_llm_call(...)` after either success or caught exception — never before, because `duration_ms` and output token counts are not known until the awaited call completes.

The emitted call MUST include the persona name, role name, model identifier drawn from the harness configuration, input/output token counts when reported by the harness, and the measured `duration_ms`. When the awaited harness call raises an exception, the decorator MUST catch, emit the span with `metadata={"error": type(exc).__name__}` and `duration_ms` equal to the elapsed time until the exception, then re-raise the original exception unchanged.

The integration SHALL be implemented via a `@traced_harness` decorator applied to each concrete subclass of `SdkHarnessAdapter`. Applying the decorator to the abstract base at `src/assistant/harnesses/base.py` does NOT propagate to subclasses that override `invoke` entirely; therefore the decorator MUST be applied to concrete implementations directly — `DeepAgentsHarness.invoke` at `src/assistant/harnesses/sdk/deep_agents.py` and the `MSAgentFrameworkHarness.invoke` stub at `src/assistant/harnesses/sdk/ms_agent_fw.py`. Future harness implementations SHALL apply the same decorator at the point of concrete subclass definition.

#### Scenario: Deep Agents harness invocation is traced

- **WHEN** `DeepAgentsHarness(persona, role).invoke(agent, "hello")` at `src/assistant/harnesses/sdk/deep_agents.py` is awaited with persona `personal` and role `assistant`
- **THEN** `get_observability_provider().trace_llm_call` MUST be called exactly once after the awaited underlying call completes
- **AND** the emitted call's kwargs MUST include `persona="personal"`, `role="assistant"`, and a `model` value drawn from the harness configuration
- **AND** the emitted `duration_ms` MUST be a non-negative float measuring the elapsed time across the awaited call

#### Scenario: Harness exception still emits trace before propagating

- **WHEN** the underlying harness raises `RuntimeError("quota exceeded")`
- **THEN** `trace_llm_call` MUST be called once with `metadata={"error": "RuntimeError"}`
- **AND** the original `RuntimeError` MUST propagate to the caller unchanged

#### Scenario: Noop provider produces no side effects

- **WHEN** the active provider is the default noop provider and `invoke` is awaited
- **THEN** the `@traced_harness` decorator MUST still invoke `trace_llm_call`
- **AND** the noop provider's method MUST return without performing any I/O or raising

#### Scenario: MSAgentFrameworkHarness stub is traced with the raised-exception path

- **WHEN** the registered `MSAgentFrameworkHarness` stub's `invoke()` is awaited (which SHALL raise `NotImplementedError` per the harness-adapter registration spec until its real implementation lands in the `ms-graph-extension` phase)
- **THEN** `@traced_harness` MUST still be applied to that stub
- **AND** `trace_llm_call` MUST be called exactly once before the `NotImplementedError` propagates
- **AND** the emitted span's `metadata` MUST contain `{"error": "NotImplementedError"}`
- **AND** the `NotImplementedError` MUST propagate to the caller unchanged
