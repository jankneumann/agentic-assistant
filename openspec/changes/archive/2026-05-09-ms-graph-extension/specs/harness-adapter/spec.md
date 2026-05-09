## REMOVED Requirements

### Requirement: MS Agent Framework Harness Registered but Stubbed

**Reason**: The MS Agent Framework harness is no longer a registered
stub. It is now a fully implemented `SdkHarnessAdapter` whose
behaviors are specified in the new `ms-agent-framework-harness`
capability. The placeholder behavior of raising `NotImplementedError`
from `create_agent()` is therefore obsolete.

**Migration**: Refer to the `ms-agent-framework-harness` capability
spec for the full set of requirements that replace this stub-state
requirement. The factory registration itself (i.e., that
`HARNESS_REGISTRY["ms_agent_framework"] = MSAgentFrameworkHarness`)
remains in place — only the stub-state behavioral requirement is
removed.

## MODIFIED Requirements

### Requirement: Harness Invocation Emits Observability Span

The system SHALL emit exactly one `trace_llm_call` observability span
per invocation of any `SdkHarnessAdapter.invoke(...)` implementation.
A `@traced_harness` decorator SHALL record the start time, await the
underlying call, and then invoke
`get_observability_provider().trace_llm_call(...)` after either
success or caught exception — never before, because `duration_ms` and
output token counts are not known until the awaited call completes.

The emitted call MUST include the persona name, role name, model
identifier drawn from the harness configuration, input/output token
counts when reported by the harness, and the measured `duration_ms`.
When the awaited harness call raises an exception, the decorator MUST
catch, emit the span with `metadata={"error": type(exc).__name__}` and
`duration_ms` equal to the elapsed time until the exception, then
re-raise the original exception unchanged.

The integration SHALL be implemented via a `@traced_harness`
decorator applied to each concrete subclass of `SdkHarnessAdapter`.
Applying the decorator to the abstract base at
`src/assistant/harnesses/base.py` does NOT propagate to subclasses
that override `invoke` entirely; therefore the decorator MUST be
applied to concrete implementations directly —
`DeepAgentsHarness.invoke` at
`src/assistant/harnesses/sdk/deep_agents.py` and the
`MSAgentFrameworkHarness.invoke` (now a fully implemented method
that awaits `agent.run`) at
`src/assistant/harnesses/sdk/ms_agent_fw.py`. Future harness
implementations SHALL apply the same decorator at the point of
concrete subclass definition.

#### Scenario: Deep Agents harness invocation is traced

- **WHEN** `DeepAgentsHarness(persona, role).invoke(agent, "hello")`
  at `src/assistant/harnesses/sdk/deep_agents.py` is awaited with
  persona `personal` and role `assistant`
- **THEN** `get_observability_provider().trace_llm_call` MUST be
  called exactly once after the awaited underlying call completes
- **AND** the emitted call's kwargs MUST include `persona="personal"`,
  `role="assistant"`, and a `model` value drawn from the harness
  configuration
- **AND** the emitted `duration_ms` MUST be a non-negative float
  measuring the elapsed time across the awaited call

#### Scenario: Harness exception still emits trace before propagating

- **WHEN** the underlying harness raises `RuntimeError("quota
  exceeded")`
- **THEN** `trace_llm_call` MUST be called once with
  `metadata={"error": "RuntimeError"}`
- **AND** the original `RuntimeError` MUST propagate to the caller
  unchanged

#### Scenario: Noop provider produces no side effects

- **WHEN** the active provider is the default noop provider and
  `invoke` is awaited
- **THEN** the `@traced_harness` decorator MUST still invoke
  `trace_llm_call`
- **AND** the noop provider's method MUST return without performing
  any I/O or raising

#### Scenario: MSAgentFrameworkHarness invoke emits trace on the success path

- **WHEN** the registered `MSAgentFrameworkHarness.invoke()` is
  awaited (which now calls the real `agent.run` from the
  `agent-framework` package per the `ms-agent-framework-harness`
  capability spec)
- **AND** the underlying `agent.run` returns the string `"hello"`
- **THEN** `@traced_harness` MUST be applied to that method
- **AND** `trace_llm_call` MUST be called exactly once after
  `agent.run` returns
- **AND** the returned value MUST equal `"hello"`

#### Scenario: MSAgentFrameworkHarness exception path still emits trace

- **WHEN** `MSAgentFrameworkHarness.invoke()` is awaited and the
  underlying `agent.run` raises `RuntimeError("model unavailable")`
- **THEN** `trace_llm_call` MUST be called once with
  `metadata={"error": "RuntimeError"}`
- **AND** the original `RuntimeError` MUST propagate to the caller
  unchanged
