# extension-registry Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
