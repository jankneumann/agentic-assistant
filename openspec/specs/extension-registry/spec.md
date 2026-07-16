# extension-registry Specification

## Purpose
Governs the `Extension` protocol and its registry: how extensions expose
tools via `as_langchain_tools()`, receive their activation config at
construction, report `HealthStatus`, emit observability spans on tool
invocation, and are built through a factory that optionally receives the
persona. It exists to keep extension implementations in the public repo
while activation configuration stays in private persona repos, so a persona
enables only the integrations it needs. Consumers are persona loading, the
harness adapters that aggregate extension tools, and health checks.
## Requirements
### Requirement: Extension Protocol

The `Extension` Protocol SHALL retain its existing `as_langchain_tools()`
and `as_ms_agent_tools()` methods. Extensions become one tool source
managed by `ToolPolicy` alongside HTTP tools and MCP servers.

The Protocol's **required** surface SHALL NOT grow lifecycle methods:
the async lifecycle hooks `initialize()`, `shutdown()`, and
`refresh_credentials()` are OPTIONAL, documented-optional members of
the extension contract (see the "Extension Lifecycle Hooks"
requirement). An extension that defines none of them MUST still
satisfy `isinstance(ext, Extension)` and MUST load unchanged — this
protects private-persona extensions that satisfy the Protocol
structurally.

#### Scenario: Extensions accessible via ToolPolicy

- **WHEN** `ToolPolicy.authorized_extensions(persona, role)` is called
- **THEN** the returned list MUST contain all loaded extensions for the
  persona
- **AND** each extension MUST satisfy `isinstance(ext, Extension)`

#### Scenario: Hook-less extension still satisfies the Protocol

- **WHEN** an extension class defines only `name`,
  `as_langchain_tools()`, `as_ms_agent_tools()`, and `health_check()`
  (no lifecycle hooks)
- **THEN** `isinstance(instance, Extension)` MUST be `True`
- **AND** `PersonaRegistry.load_extensions()` MUST return the instance

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

### Requirement: Extension config is passed to constructor

Each stub's `create_extension` SHALL pass its `config` argument to the
underlying class constructor, and the resulting instance SHALL expose
`self.scopes` when the config contains a `scopes` key.

#### Scenario: Scopes are stored on the instance

- **WHEN** `create_extension({"scopes": ["s1", "s2"]})` is called
- **THEN** the returned instance's `.scopes` attribute MUST equal
  `["s1", "s2"]`

#### Scenario: Missing scopes default to empty list

- **WHEN** `create_extension({})` is called
- **THEN** the returned instance's `.scopes` attribute MUST equal `[]`

### Requirement: Extension Tool Invocations Emit Observability Span

The system SHALL ensure that every LangChain `StructuredTool` returned by any `Extension.as_langchain_tools()` emits a `trace_tool_call` observability span on each invocation. Because `Extension` is a `typing.Protocol` (not a base class that carries behavior for subclasses), the wrapping SHALL be performed at the aggregation sites that compose extension tool bundles — see the `capability-resolver` capability spec for the authoritative list of aggregation sites and the shared `wrap_extension_tools` helper. Individual extension implementations SHALL NOT add tracing code themselves.

The emitted call MUST include `tool_name` (the StructuredTool's `name`), `tool_kind="extension"`, `persona`, `role`, and `duration_ms`. When the tool's `_run` or `_arun` raises, the span MUST be emitted with `error=<exception type name>` before the exception propagates.

Wrapping SHALL preserve each tool's original `name`, `description`, and `args_schema` so that agents and tool-discovery consumers see no change in the tool's public contract.

#### Scenario: Extension tool invocation emits trace_tool_call

- **WHEN** an extension returns a `StructuredTool` named `gmail.search` and `gmail.search.invoke({"query": "foo"})` is called with persona `personal` and role `assistant`
- **THEN** `trace_tool_call` MUST be called exactly once
- **AND** the emitted call's kwargs MUST include `tool_name="gmail.search"`, `tool_kind="extension"`, `persona="personal"`, and `role="assistant"`

#### Scenario: Tool exception emits trace before propagating

- **WHEN** a wrapped tool's `_run` raises `ValueError("invalid query")`
- **THEN** `trace_tool_call` MUST be called with `error="ValueError"`
- **AND** the exception MUST propagate to the caller

#### Scenario: Tool metadata passthrough is preserved

- **WHEN** an extension returns a `StructuredTool` with `name="x"`, `description="y"`, and a specific `args_schema`
- **THEN** the wrapped tool exposed by `as_langchain_tools()` MUST have the identical `name`, `description`, and `args_schema`

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

### Requirement: Extension Lifecycle Hooks

The system SHALL define three optional async lifecycle hooks on the
extension contract:

- `initialize() -> None` — called once after the extension is loaded,
  before its tools are exposed (establish connections, warm caches,
  validate configuration).
- `shutdown() -> None` — called on graceful teardown (close
  connections, flush buffers). Implementations MUST be idempotent.
- `refresh_credentials() -> None` — proactive credential refresh seam
  (OAuth token refresh, key rotation) for periodic or on-demand
  invocation by lifecycle consumers (P13 security-hardening, P14
  google-extensions).

Because `Extension` is a `typing.Protocol`, the hooks SHALL NOT be
required Protocol members; callers MUST discover each hook via
`callable(getattr(ext, "<hook>", None))` and treat an absent hook as
a no-op. Callers SHALL invoke a present hook tolerantly: await the
result only when it is awaitable, so a synchronous hook on an
out-of-tree extension is accepted.

The system SHALL ship `ExtensionBase` in
`src/assistant/extensions/base.py` — a plain base class providing
async no-op implementations of all three hooks — and every concrete
extension class in `src/assistant/extensions/` (the `StubExtension`
shared by `gmail`/`gcal`/`gdrive` and the four real MS extension
classes) SHALL subclass it.

The four real MS extensions (`ms_graph`, `outlook`, `teams`,
`sharepoint`) SHALL override:

- `shutdown()` — await the injected client's idempotent `aclose()`,
  closing the per-extension `GraphClient` connection pool.
- `refresh_credentials()` — delegate to the injected client's
  `refresh_credentials()` when the client exposes one; otherwise
  no-op (mock and third-party `CloudGraphClient` implementations
  without the method MUST NOT cause an error).

They SHALL NOT override `initialize()` to acquire tokens eagerly —
the delegated MSAL flow would trigger an interactive prompt at
persona load.

#### Scenario: ExtensionBase provides no-op lifecycle defaults

- **WHEN** any concrete extension in `src/assistant/extensions/` is
  instantiated
- **THEN** `initialize()`, `shutdown()`, and `refresh_credentials()`
  MUST be awaitable on it
- **AND** awaiting the `ExtensionBase` defaults MUST return `None`
  without side effects

#### Scenario: Stub extensions carry no-op hooks

- **WHEN** `create_extension({})` is called for any of `gmail`,
  `gcal`, `gdrive`
- **THEN** awaiting `initialize()`, `shutdown()`, and
  `refresh_credentials()` on the instance MUST NOT raise

#### Scenario: MS extension shutdown closes the injected client

- **WHEN** any of the four real extensions is constructed with an
  injected client and `await ext.shutdown()` is called
- **THEN** the client's `aclose()` MUST have been awaited

#### Scenario: MS extension refresh_credentials delegates to the client

- **WHEN** any of the four real extensions is constructed with an
  injected client that exposes an async `refresh_credentials()`
- **AND** `await ext.refresh_credentials()` is called
- **THEN** the client's `refresh_credentials()` MUST have been awaited

#### Scenario: MS extension refresh_credentials tolerates a client without the method

- **WHEN** any of the four real extensions is constructed with an
  injected client that does NOT expose `refresh_credentials`
- **AND** `await ext.refresh_credentials()` is called
- **THEN** no exception MUST be raised

