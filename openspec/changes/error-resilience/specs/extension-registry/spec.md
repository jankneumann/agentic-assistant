# extension-registry Specification Delta

## ADDED Requirements

### Requirement: Extension Health Check Returns HealthStatus

The `Extension` Protocol's `health_check()` method SHALL return a `HealthStatus` value (from the `error-resilience` capability), replacing the prior `bool` return type. Every concrete extension implementation in `src/assistant/extensions/` MUST honour this contract — both the seven stubs that ship today (`ms_graph`, `teams`, `sharepoint`, `outlook`, `gmail`, `gcal`, `gdrive`) and any future implementation written in P5 / P14 or in a private persona submodule.

`HealthStatus` carries enough state for an agent to truthfully announce backend availability: `state` (one of `OK`, `DEGRADED`, `UNAVAILABLE`, `UNKNOWN`), `reason` (human-readable), `last_error` (string summary if the most recent probe failed), `checked_at` (timestamp), and `breaker_key` (the circuit-breaker registry key associated with this extension, when applicable).

Extension stubs that do not yet implement a real backend probe SHALL return the result of `default_health_status_for_unimplemented(extension_name)` so the entire stub set produces a uniform `HealthState.UNKNOWN` response with `reason="extension is a stub"`.

#### Scenario: Protocol return type is HealthStatus

- **WHEN** the `Extension` Protocol is type-checked under mypy
- **THEN** `Extension.health_check.__annotations__["return"]` MUST resolve to `HealthStatus` (not `bool`)

#### Scenario: Stub returns UNKNOWN HealthStatus

- **WHEN** `await create_extension({}).health_check()` is called on any of the seven stub extensions
- **THEN** the returned object MUST be a `HealthStatus` instance
- **AND** `state` MUST equal `HealthState.UNKNOWN`
- **AND** `reason` MUST equal `"extension is a stub"`

#### Scenario: Real extension can derive HealthStatus from its breaker

- **WHEN** a future extension implementation calls `health_status_from_breaker(self._breaker, key=f"extension:{self.name}")`
- **THEN** the returned `HealthStatus` MUST have `breaker_key="extension:<name>"`
- **AND** `state` MUST reflect the breaker's current state per the mapping defined in the `error-resilience` capability

## MODIFIED Requirements

### Requirement: Stub Implementations for All Configured Extensions

The system SHALL ship stub implementations for `ms_graph`, `teams`, `sharepoint`, `outlook`, `gmail`, `gcal`, and `gdrive` in `src/assistant/extensions/`, each exposing a `create_extension(config: dict)` factory returning an `Extension`-compatible instance.

#### Scenario: Each stub exports create_extension

- **WHEN** the module `assistant.extensions.<name>` is imported for each of the seven extension names
- **THEN** each module MUST define a callable `create_extension`

#### Scenario: Stubs return empty tool lists

- **WHEN** `create_extension({}).as_langchain_tools()` is called on any stub
- **THEN** it MUST return `[]`
- **AND** `as_ms_agent_tools()` MUST return `[]`

#### Scenario: Stub health_check returns UNKNOWN HealthStatus

- **WHEN** `await create_extension({}).health_check()` is called on any stub
- **THEN** the returned object MUST be a `HealthStatus` instance with `state=HealthState.UNKNOWN`
- **AND** `reason` MUST equal `"extension is a stub"`
