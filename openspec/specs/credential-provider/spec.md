# credential-provider Specification

## Purpose
TBD - created by archiving change capability-protocols-v2. Update Purpose after archive.
## Requirements
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
implementation that resolves a ref against an optional persona-scoped
namespace first and the process environment second. Without a scoped
namespace it preserves the exact semantics of the historical `_env()`
indirection: `get_credential(ref)` returns `os.environ.get(ref, "")`,
and an empty or missing `ref` returns `""` without error — a fresh
standalone clone (e.g., the GX10 node) stays bootable with no vault
deployed. With a scoped namespace (constructor argument `scoped`,
typically loaded from a persona `.env` file), a ref *present* in the
namespace resolves there — including to an empty value, which
deliberately masks the process variable — and only absent refs fall
back to `os.environ`. The scoped namespace MUST NOT be written into
the process environment.

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

#### Scenario: Scoped value wins over the process environment

- **WHEN** the process environment contains `API_TOKEN=process-value`
- **AND** `EnvCredentialProvider(scoped={"API_TOKEN":
  "scoped-value"}).get_credential("API_TOKEN")` is called
- **THEN** it MUST return `"scoped-value"`

#### Scenario: Empty scoped value masks the process variable

- **WHEN** the process environment contains `API_TOKEN=process-value`
- **AND** the scoped namespace contains `API_TOKEN` with an empty
  value
- **THEN** `get_credential("API_TOKEN")` MUST return `""`

#### Scenario: Unscoped ref falls back to the process environment

- **WHEN** the scoped namespace does not contain `OTHER_TOKEN`
- **AND** the process environment contains `OTHER_TOKEN=fallback`
- **THEN** `get_credential("OTHER_TOKEN")` MUST return `"fallback"`

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

### Requirement: Per-Persona Credential Namespace

The system SHALL support a git-ignored `.env` file in each persona
directory whose `KEY=VALUE` entries load into that persona's SCOPED
credential namespace — never into the process `os.environ`.
Resolution order is persona `.env` first, process environment
fallback. Two personas loaded in the same process MUST resolve the
same ref name independently, with neither namespace visible to the
other or to the process environment. The parser SHALL be minimal
(comments, blank lines, optional `export` prefix, one pair of
surrounding quotes) and SHALL skip malformed lines with a warning
that names the line number only — never the line content. The scoped
namespace is designed to map 1:1 onto per-persona OpenBao mounts
(P25): a vault-backed provider implements the same precedence
(persona mount first, process environment as the standalone/dev
fallback) behind the unchanged protocol.

#### Scenario: Two personas resolve the same ref differently

- **WHEN** persona `alpha`'s `.env` sets `SHARED_KEY=a-value` and
  persona `beta`'s `.env` sets `SHARED_KEY=b-value`
- **AND** both personas are loaded in one process
- **THEN** `alpha`'s provider MUST resolve `SHARED_KEY` to
  `"a-value"` and `beta`'s to `"b-value"`
- **AND** `SHARED_KEY` MUST NOT appear in `os.environ`

#### Scenario: Persona without a .env keeps process-env behavior

- **WHEN** a persona directory contains no `.env` file
- **THEN** every ref MUST resolve against the process environment
  exactly as before this change

#### Scenario: Malformed .env line is skipped without leaking content

- **WHEN** a persona `.env` contains a line that is not a valid
  `KEY=VALUE` assignment
- **THEN** the remaining valid entries MUST still load
- **AND** the emitted warning MUST NOT include the malformed line's
  content

### Requirement: Persona Loading Uses the Persona-Scoped Provider

The persona registry SHALL construct (or accept via an injected
`credential_provider_factory(persona_name, persona_dir)`) one
`CredentialProvider` per persona at load time, expose it as
`PersonaConfig.credentials`, and resolve every persona-config secret
(`database.url_env`, `graphiti.*_env`, `auth.config.*_env`,
`tool_sources.*.base_url_env`) through it. Downstream consumers —
HTTP tool discovery auth headers, model bindings in the SDK
harnesses, the graphiti factory, and MSAL strategy construction —
SHALL resolve their credential refs through `PersonaConfig.credentials`
rather than the process environment. The provider field MUST be
excluded from the dataclass repr so the scoped namespace cannot leak
through logs.

#### Scenario: Injected provider sees every persona secret read

- **WHEN** a persona is loaded with a custom
  `credential_provider_factory` injected
- **THEN** the database URL, auth config values, and tool-source base
  URLs MUST be obtained via `get_credential(...)` on that provider
- **AND** not via direct `os.environ` reads

#### Scenario: Harness model credentials use the persona provider

- **WHEN** an SDK harness binds a `ModelRef` with a `credential_ref`
- **AND** no explicit credential provider was injected into the
  harness
- **THEN** the ref MUST resolve through `PersonaConfig.credentials`

