## ADDED Requirements

### Requirement: Extension Factory Contract Accepts Optional Persona

The system SHALL extend the `create_extension` factory contract to
accept a keyword-only `persona: PersonaConfig | None = None`
argument in addition to the existing `config: dict` argument. The
new signature is `create_extension(config: dict, *, persona:
PersonaConfig | None = None) -> Extension`. Stub factories
(`gmail`, `gcal`, `gdrive`) SHALL accept the new argument and
ignore it. Real extension factories
(`ms_graph`, `outlook`, `teams`, `sharepoint`) SHALL use `persona`
to construct their own `MSALStrategy` (via `create_msal_strategy`)
and per-extension `GraphClient`, then pass the client into the
extension class constructor.

`PersonaRegistry.load_extensions()` SHALL pass `persona=<the
persona>` to every factory call. Existing third-party extension
factories that do not accept a `persona` argument MUST raise a
clear `TypeError` at load time, identifying the offending
extension name and the migration recipe.

#### Scenario: PersonaRegistry passes persona to all factories

- **WHEN** `PersonaRegistry.load_extensions(persona)` is called for a
  persona with `extensions: ms_graph, outlook, gmail` enabled
- **THEN** each loaded module's `create_extension` MUST be called
  with both the per-extension config dict AND the keyword argument
  `persona=<the persona>`
- **AND** stub factories (`gmail`) MUST accept this without raising

#### Scenario: Real factory constructs MSALStrategy and GraphClient internally

- **WHEN** the `outlook` factory `create_extension({}, persona=p)`
  is called with a persona configured for `auth.ms.flow=interactive`
- **THEN** the factory MUST call `create_msal_strategy(p)` to obtain
  the strategy
- **AND** the factory MUST construct
  `GraphClient(extension_name="outlook", strategy=<strategy>,
  scopes=<resolved scopes>)`
- **AND** the factory MUST pass that client into
  `OutlookExtension.__init__` as the `client` argument

#### Scenario: Stub factory ignores persona argument

- **WHEN** the `gmail` stub factory `create_extension({},
  persona=p)` is called
- **THEN** the returned object MUST be a `StubExtension` instance
- **AND** no MSAL strategy or GraphClient MUST be constructed

#### Scenario: Real factory called with persona=None raises actionable TypeError

- **WHEN** any of the four real factories
  (`ms_graph`, `outlook`, `teams`, `sharepoint`) is called as
  `create_extension({}, persona=None)` (or with `persona` omitted,
  which defaults to `None` per the Protocol signature)
- **THEN** a `TypeError` MUST be raised before any MSAL strategy or
  GraphClient construction is attempted
- **AND** the error message MUST identify the offending extension
  name and explicitly state that real Microsoft 365 extensions
  require a non-None `persona` argument carrying `auth.ms`
  configuration
- **AND** the error message MUST cite the persona YAML key path
  (`extensions.<name>` and `auth.ms`) so the operator can fix the
  persona config or the test harness

#### Scenario: Legacy factory signature raises actionable TypeError

- **WHEN** `PersonaRegistry.load_extensions` calls a third-party
  factory whose signature does not accept the keyword argument
  `persona`
- **THEN** a `TypeError` MUST be raised
- **AND** the error message MUST identify the offending extension
  name and instruct the operator to add `*, persona:
  PersonaConfig | None = None` to the factory signature

## MODIFIED Requirements

### Requirement: Stub Implementations for All Configured Extensions

The system SHALL ship stub implementations for `gmail`, `gcal`, and
`gdrive` in `src/assistant/extensions/`, each exposing a
`create_extension(config: dict)` factory returning an
`Extension`-compatible instance whose tool methods return empty
lists. The extensions `ms_graph`, `teams`, `sharepoint`, and `outlook`
SHALL no longer ship as stubs — those four are real implementations
delivered by the `ms-extensions` capability and import their
domain-specific tooling rather than `StubExtension`.

#### Scenario: Each remaining stub exports create_extension

- **WHEN** the module `assistant.extensions.<name>` is imported for
  each of `gmail`, `gcal`, and `gdrive`
- **THEN** each module MUST define a callable `create_extension`

#### Scenario: Remaining stubs return empty tool lists

- **WHEN** `create_extension({}).as_langchain_tools()` is called on
  any of the three remaining stubs (`gmail`, `gcal`, `gdrive`)
- **THEN** it MUST return `[]`
- **AND** `as_ms_agent_tools()` MUST return `[]`

#### Scenario: ms_graph/teams/sharepoint/outlook no longer return empty tool lists

- **WHEN** `create_extension({}, client=mock_client).as_langchain_tools()`
  is called on any of the four real extensions
- **THEN** the returned list MUST be non-empty
- **AND** the same MUST hold for `as_ms_agent_tools()`

### Requirement: Extension Health Check Returns HealthStatus

The `Extension` Protocol's `health_check()` method SHALL return a
`HealthStatus` value (from the `error-resilience` capability),
replacing the prior `bool` return type. Every concrete extension
implementation in `src/assistant/extensions/` MUST honour this
contract — the three stubs that ship for `gmail`/`gcal`/`gdrive`,
the four real implementations for
`ms_graph`/`teams`/`sharepoint`/`outlook`, and any future
implementation written in P14 or in a private persona submodule.

`HealthStatus` carries enough state for an agent to truthfully
announce backend availability: `state` (one of `OK`, `DEGRADED`,
`UNAVAILABLE`, `UNKNOWN`), `reason` (human-readable), `last_error`
(string summary if the most recent probe failed), `checked_at`
(timestamp), and `breaker_key` (the circuit-breaker registry key
associated with this extension, when applicable).

Extension stubs that do not yet implement a real backend probe SHALL
return the result of `default_health_status_for_unimplemented(extension_name)`
so the entire stub set produces a uniform `HealthState.UNKNOWN`
response with `reason="extension is a stub"`. Real implementations
(the four ms-extensions) SHALL derive their status from the
extension-scoped circuit breaker via
`health_status_from_breaker(self._breaker, key=f"extension:{self.name}")`.

#### Scenario: Protocol return type is HealthStatus

- **WHEN** the `Extension` Protocol is type-checked under mypy
- **THEN** `Extension.health_check.__annotations__["return"]` MUST
  resolve to `HealthStatus` (not `bool`)

#### Scenario: Stub returns UNKNOWN HealthStatus

- **WHEN** `await create_extension({}).health_check()` is called on
  any of the three remaining stub extensions (`gmail`, `gcal`,
  `gdrive`)
- **THEN** the returned object MUST be a `HealthStatus` instance
- **AND** `state` MUST equal `HealthState.UNKNOWN`
- **AND** `reason` MUST equal `"extension is a stub"`

#### Scenario: Real extension derives HealthStatus from its breaker

- **WHEN** any of the four real extensions
  (`ms_graph`/`teams`/`sharepoint`/`outlook`) calls
  `health_status_from_breaker(self._breaker, key=f"extension:{self.name}")`
- **THEN** the returned `HealthStatus` MUST have
  `breaker_key="extension:<name>"`
- **AND** `state` MUST reflect the breaker's current state per the
  mapping defined in the `error-resilience` capability

#### Scenario: Runtime conformance check rejects bool-returning health_check

- **WHEN** the persona registry loads any extension and calls its
  `health_check()` for the first time
- **AND** the awaited return value is **not** a `HealthStatus`
  instance (for example a legacy out-of-tree extension still returns
  `True`)
- **THEN** a `TypeError` MUST be raised identifying the offending
  extension by `name`, the actual return type, and the migration
  recipe (`return default_health_status_for_unimplemented(self.name)`)
- **AND** the error message MUST cite `docs/gotchas.md` for the
  migration note
