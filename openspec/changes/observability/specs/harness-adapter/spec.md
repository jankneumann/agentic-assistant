# harness-adapter Specification Delta

## ADDED Requirements

### Requirement: Harness Invocation Emits Observability Span

The system SHALL emit an observability `trace_llm_call` for every invocation of any `HarnessAdapter.invoke(...)` implementation by calling `get_observability_provider().trace_llm_call(...)` immediately before and after the awaited harness call. The emitted call MUST include the persona name, role name, model identifier drawn from the harness configuration, input/output token counts when reported by the harness, and the measured `duration_ms`.

When the harness call raises an exception, the span MUST still be emitted (with `metadata={"error": type(exc).__name__}`) before the exception is re-raised to the caller.

The integration SHALL be implemented via a `@traced_harness` decorator applied to `invoke` in both `src/assistant/harnesses/base.py` (for the abstract base) and `src/assistant/harnesses/deep_agents.py` (for the Deep Agents concrete implementation), so that future harness implementations inherit the behavior automatically.

#### Scenario: Deep Agents harness invocation is traced

- **WHEN** `DeepAgentsHarness(config).invoke(agent, "hello")` is awaited with persona `personal` and role `assistant`
- **THEN** `get_observability_provider().trace_llm_call` MUST be called exactly once
- **AND** the emitted call's kwargs MUST include `persona="personal"`, `role="assistant"`, `model=config.model`
- **AND** the emitted `duration_ms` MUST be a non-negative float

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
