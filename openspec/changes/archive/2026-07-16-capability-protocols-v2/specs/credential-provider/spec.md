# credential-provider Specification (delta)

## ADDED Requirements

### Requirement: CredentialProvider Protocol

The system SHALL define a `CredentialProvider` runtime-checkable
Protocol with the method `get_credential(ref: str) → str` — the single
lookup seam through which all secret and API-key reads flow. A `ref`
is an opaque lookup key (today: an environment-variable name; under a
vault backend: a vault path/key), never a secret value itself. The
protocol is backend-agnostic by design: the OpenBao backend (P25)
implements the same protocol and swaps in via injection without
touching any call site. Distinguishing inbound credentials (who may
call us) from outbound credentials (what we present on the user's
behalf) is explicitly P25 scope — this seam covers outbound lookup
only.

#### Scenario: Conforming implementation satisfies Protocol

- **WHEN** a class implements `get_credential` with the correct
  signature
- **THEN** `isinstance(instance, CredentialProvider)` MUST return
  `True`

#### Scenario: Backend swap requires no call-site changes

- **WHEN** a vault-backed `CredentialProvider` is injected in place of
  the default implementation
- **THEN** every consuming call site MUST work unchanged — call sites
  depend only on the protocol and the `ref` vocabulary

### Requirement: Env Default Implementation

The system SHALL provide an `EnvCredentialProvider` default
implementation preserving the exact semantics of the existing `_env()`
indirection: `get_credential(ref)` returns `os.environ.get(ref, "")`,
and an empty or missing `ref` returns `""` without error. This default
keeps a fresh standalone clone (e.g., the GX10 node) bootable with no
vault deployed.

#### Scenario: Present variable resolves

- **WHEN** the environment contains `GMAIL_TOKEN=abc123`
- **AND** `EnvCredentialProvider().get_credential("GMAIL_TOKEN")` is
  called
- **THEN** it MUST return `"abc123"`

#### Scenario: Missing or empty ref returns empty string

- **WHEN** `get_credential("")` or `get_credential("UNSET_VAR")` is
  called with no such environment variable set
- **THEN** it MUST return `""`
- **AND** no exception MUST be raised

### Requirement: Credential Reads Flow Through the Seam

The system SHALL route every secret/API-key read through the active
`CredentialProvider` rather than reading the process environment
directly. The known call-site families are: persona configuration
env indirections (the `*_env` keys resolved by the `_env()` helpers in
`core/persona.py` and `core/graphiti.py`), HTTP tool-source auth
headers, and `ModelRef.credential_ref` resolution inside the model
bindings. New code MUST NOT introduce direct `os.environ` secret
reads outside a `CredentialProvider` implementation; the sandbox
credentials plane and P13 per-persona scoping build on this seam
being the only doorway.

#### Scenario: Persona config secrets resolve via the provider

- **WHEN** a persona declares `database.url_env: "PERSONAL_DB_URL"`
- **AND** the persona is loaded with a custom `CredentialProvider`
  injected
- **THEN** the database URL MUST be obtained via
  `get_credential("PERSONAL_DB_URL")` on that provider
- **AND** not via a direct `os.environ` read

#### Scenario: Model bindings resolve credential_ref via the provider

- **WHEN** a model binding adapts a `ModelRef` with
  `credential_ref="OPENROUTER_API_KEY"`
- **THEN** the API key MUST be obtained via
  `get_credential("OPENROUTER_API_KEY")` on the active provider
