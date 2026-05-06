## ADDED Requirements

### Requirement: MSAL Strategy Protocol

The system SHALL define an `MSALStrategy` Protocol in
`src/assistant/core/msal_auth.py` exposing exactly one async method
`acquire_token(scopes: list[str], *, force_refresh: bool = False) ->
str` that returns a bearer access token suitable for the
`Authorization: Bearer <token>` header on Microsoft Graph requests.
Concrete strategy implementations SHALL satisfy this Protocol via
`runtime_checkable`.

#### Scenario: Protocol returns access token string

- **WHEN** `acquire_token(["User.Read"])` is awaited on any concrete
  strategy implementation
- **THEN** the returned value MUST be a `str`
- **AND** the value MUST be non-empty when the underlying MSAL call
  succeeds

#### Scenario: Protocol is runtime-checkable

- **WHEN** `isinstance(InteractiveDelegatedStrategy(...), MSALStrategy)`
  is evaluated
- **THEN** it MUST return `True`
- **AND** the same MUST hold for `ClientCredentialsStrategy(...)`

### Requirement: Interactive Delegated Strategy

The system SHALL provide `InteractiveDelegatedStrategy` that uses
`msal.PublicClientApplication` to acquire delegated user tokens.
On the first call for a given persona, the strategy SHALL invoke
`acquire_token_interactive()` (opening the system browser) and persist
the returned account + refresh token via a serializable token cache.
On subsequent calls, the strategy SHALL prefer
`acquire_token_silent()` and only fall back to the interactive flow
when silent acquisition fails.

#### Scenario: First call opens interactive flow when cache is empty

- **WHEN** `InteractiveDelegatedStrategy(persona, tenant_id, client_id)`
  is constructed against an empty token cache
- **AND** `acquire_token(["Mail.Read"])` is awaited
- **THEN** `msal.PublicClientApplication.acquire_token_interactive` MUST
  be called with the requested scope set
- **AND** the resulting refresh token MUST be persisted to the
  configured cache path

#### Scenario: Subsequent call uses silent flow

- **WHEN** the token cache already holds a valid refresh token
- **AND** `acquire_token(["Mail.Read"])` is awaited
- **THEN** `msal.PublicClientApplication.acquire_token_silent` MUST be
  called first
- **AND** the interactive flow MUST NOT be invoked

#### Scenario: Silent failure falls back to interactive

- **WHEN** `acquire_token_silent` returns `None` (refresh token expired
  or revoked)
- **THEN** the strategy MUST fall back to `acquire_token_interactive`
- **AND** the new tokens MUST be persisted to the cache

#### Scenario: force_refresh bypasses silent flow

- **WHEN** `acquire_token(["Mail.Read"], force_refresh=True)` is awaited
- **THEN** `acquire_token_silent` MUST NOT be called
- **AND** `acquire_token_interactive` MUST be invoked

#### Scenario: Device-code fallback when MSAL_FALLBACK_DEVICE_CODE is set

- **WHEN** the environment variable `MSAL_FALLBACK_DEVICE_CODE=1` is
  set
- **AND** `acquire_token(["Mail.Read"])` is awaited on
  `InteractiveDelegatedStrategy` against an empty cache
- **THEN** `initiate_device_flow()` MUST be invoked instead of
  `acquire_token_interactive()`
- **AND** the device-code prompt MUST be written to stderr for the
  operator to read

### Requirement: Client Credentials Strategy

The system SHALL provide `ClientCredentialsStrategy` that uses
`msal.ConfidentialClientApplication.acquire_token_for_client()` to
acquire app-only tokens for unattended scenarios. The strategy SHALL
NOT use any token cache; tokens live only as long as their server-side
TTL.

#### Scenario: Strategy uses ConfidentialClientApplication

- **WHEN** `ClientCredentialsStrategy(tenant_id, client_id,
  client_secret)` is constructed
- **AND** `acquire_token(["https://graph.microsoft.com/.default"])` is
  awaited
- **THEN** `msal.ConfidentialClientApplication.acquire_token_for_client`
  MUST be called with the requested scope set
- **AND** no token cache file MUST be created

#### Scenario: Strategy rejects user-scoped scopes

- **WHEN** `acquire_token(["Mail.Read"])` is called on a
  `ClientCredentialsStrategy` instance
- **THEN** `MSALAuthenticationError` MUST be raised
- **AND** the error message MUST direct the caller to use a `.default`
  scope or switch to `InteractiveDelegatedStrategy`

### Requirement: Token Cache File Discipline

The system SHALL write the MSAL token cache for a persona named `P` to
`personas/P/.cache/msal_token_cache.json`. Cache writes SHALL be
atomic (write to a `.tmp` sibling, then `os.rename`). The directory
SHALL be created with mode `0o700` and the file SHALL be written with
mode `0o600`. On read, a missing cache file MUST be treated as an
empty cache without error.

#### Scenario: First write creates directory with restrictive permissions

- **WHEN** the strategy persists a token cache for persona `personal`
- **AND** the directory `personas/personal/.cache/` does not exist
- **THEN** the directory MUST be created
- **AND** its mode bits MUST equal `0o700`

#### Scenario: File is written with mode 0o600

- **WHEN** the strategy persists a token cache to
  `personas/personal/.cache/msal_token_cache.json`
- **THEN** the file's mode bits MUST equal `0o600`
- **AND** no other process MUST have read or write access

#### Scenario: Atomic write via tmp + rename

- **WHEN** the strategy persists a token cache
- **THEN** the cache MUST first be written to
  `msal_token_cache.json.tmp`
- **AND** then renamed atomically to `msal_token_cache.json`

#### Scenario: Missing cache file yields empty cache without error

- **WHEN** an `InteractiveDelegatedStrategy` is constructed for a
  persona whose `.cache/msal_token_cache.json` does not exist
- **THEN** the strategy MUST initialize with an empty
  `SerializableTokenCache`
- **AND** no exception MUST be raised

#### Scenario: Permission audit fails fast on broken filesystem state

- **WHEN** the cache directory exists with mode bits including any of
  `0o077` (group or other access)
- **AND** the strategy attempts to write tokens
- **THEN** an `MSALAuthenticationError` MUST be raised before the
  write
- **AND** the error message MUST instruct the operator to run `chmod
  700 personas/<name>/.cache/`

### Requirement: Strategy Selection by Persona Configuration

The system SHALL provide a factory `create_msal_strategy(persona:
PersonaConfig) -> MSALStrategy` that selects the concrete strategy
class based on `persona.auth.ms.flow` (one of `interactive` or
`client_credentials`). The factory SHALL resolve credential
environment variable names through the existing `_env()` pattern in
`core/persona.py`.

#### Scenario: interactive flow returns InteractiveDelegatedStrategy

- **WHEN** `persona.auth.ms.flow == "interactive"` and
  `tenant_id_env`/`client_id_env` are populated
- **AND** `create_msal_strategy(persona)` is called
- **THEN** the returned object MUST be an
  `InteractiveDelegatedStrategy` instance

#### Scenario: client_credentials flow returns ClientCredentialsStrategy

- **WHEN** `persona.auth.ms.flow == "client_credentials"` and
  `tenant_id_env`/`client_id_env`/`client_secret_env` are populated
- **AND** `create_msal_strategy(persona)` is called
- **THEN** the returned object MUST be a `ClientCredentialsStrategy`
  instance

#### Scenario: Missing required env raises with actionable message

- **WHEN** `persona.auth.ms.flow == "client_credentials"` but
  `client_secret_env` resolves to an empty string
- **AND** `create_msal_strategy(persona)` is called
- **THEN** `MSALAuthenticationError` MUST be raised
- **AND** the message MUST identify the missing env var name and the
  persona

### Requirement: Authentication Errors Do Not Retry

The system SHALL ensure that `MSALAuthenticationError` raised from any
strategy method propagates immediately without going through the P9
`@resilient_http` retry layer. Authentication errors are not transient
and retrying with the same expired credential is wasteful.

#### Scenario: 401-equivalent auth error propagates without retry

- **WHEN** an MSAL call returns an error response that the strategy
  classifies as authentication failure (e.g., `invalid_grant`,
  `interaction_required`)
- **THEN** `MSALAuthenticationError` MUST be raised on the first
  attempt
- **AND** the retry layer MUST NOT make additional attempts

#### Scenario: Error string is sanitized

- **WHEN** `MSALAuthenticationError("invalid_grant: token <secret>")`
  is constructed and stringified
- **THEN** the resulting string MUST NOT contain the literal token
  value
- **AND** any candidate access-token-shaped substring MUST be replaced
  with `[REDACTED]`
