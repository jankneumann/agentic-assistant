# credential-provider Specification (delta)

## ADDED Requirements

### Requirement: OpenBao Credential Backend

The system SHALL provide an `OpenBaoCredentialProvider` implementing
the `CredentialProvider` protocol against an OpenBao
(Vault-compatible) server as a thin httpx client (no `hvac`, no new
dependencies). The per-persona vault namespace SHALL map 1:1 onto the
P13 persona-scoped namespace semantics: a ref `<REF>` for persona
`<p>` is the KV v2 secret at `<mount>/data/<p>/<REF>` (read via
`GET /v1/<mount>/data/<p>/<REF>`) holding the credential under the
data key `value`; a ref PRESENT in the vault namespace wins — even
with an empty value, which deliberately masks the lower tiers — and
an absent ref (HTTP 404) falls through to the layered
`EnvCredentialProvider` (persona `.env` first, process environment
second). Authentication SHALL use AppRole login
(`POST /v1/auth/approle/login`), caching the client token and
proactively re-acquiring it a configurable margin BEFORE its lease
TTL expires (a lease duration of `0` never expires). Any OpenBao
failure — unreachable server, non-200 response, malformed body —
SHALL degrade to the env fallback with a WARNING (logged once until
recovery) and MUST never be fatal: a fresh standalone clone with no
vault deployed boots exactly as before.

#### Scenario: KV read resolves through the per-persona path

- **WHEN** persona `fixture`'s provider resolves ref
  `OPENROUTER_API_KEY`
- **THEN** the client MUST log in via AppRole and GET
  `/v1/secret/data/fixture/OPENROUTER_API_KEY` with the vault token
- **AND** return the secret's `value` data key

#### Scenario: Present-but-empty vault value masks the env tier

- **WHEN** the vault secret for a ref exists with an empty `value`
- **AND** the env fallback would resolve the same ref to a non-empty
  value
- **THEN** `get_credential` MUST return `""`

#### Scenario: Absent ref falls back to the env tiers

- **WHEN** the vault returns 404 for a ref
- **AND** the layered env provider resolves it
- **THEN** the env value MUST be returned

#### Scenario: Token renewed before TTL expiry

- **WHEN** a cached token's lease is inside the renewal margin but
  not yet expired
- **AND** a credential is read
- **THEN** the client MUST re-authenticate first and use the fresh
  token on the read

#### Scenario: Unreachable OpenBao degrades with a single warning

- **WHEN** the OpenBao server is unreachable across multiple reads
- **THEN** every read MUST resolve through the env fallback
- **AND** exactly one WARNING MUST be logged until the server
  recovers
- **AND** no exception MUST escape to the caller

### Requirement: Persona Credentials Backend Selection

The system SHALL support a persona `credentials:` section selecting
the credential backend: `backend: env` (or an absent section) keeps
the P13 persona-scoped env provider unchanged; `backend: openbao`
requires non-empty `url_env`, `role_id_env`, and `secret_id_env`
(names of the refs holding the OpenBao address and AppRole
credentials — never secret values) and an optional `mount` (default
`secret`). The section SHALL be validated at persona load with the
actionable-error posture (unknown keys, unknown backends, and missing
refs fail load naming the offender). The bootstrap refs SHALL resolve
through the persona-scoped env provider — never raw `os.environ` —
and bootstrap refs that resolve empty SHALL degrade to the env
provider with a WARNING (never fatal). The backend selection SHALL be
wired through `PersonaRegistry` at the existing
`credential_provider_factory` injection point: an injected factory
still wins unchanged.

#### Scenario: Invalid backend fails persona load

- **WHEN** a persona declares `credentials: {backend: not-a-backend}`
- **THEN** persona load MUST raise an error naming the invalid
  backend

#### Scenario: Unconfigured OpenBao degrades to env

- **WHEN** a persona declares `backend: openbao` but the bootstrap
  refs resolve empty
- **THEN** persona load MUST succeed with the env provider
- **AND** a WARNING MUST name the unresolved refs

#### Scenario: Injected factory still wins

- **WHEN** a `credential_provider_factory` is injected into the
  registry
- **AND** the persona declares `backend: openbao`
- **THEN** the factory's provider MUST be used
