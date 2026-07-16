# http-tools Specification (delta)

## MODIFIED Requirements

### Requirement: Auth Header Resolution

The system SHALL provide `resolve_auth_header(auth_header_config,
credentials=None)` that reads a persona's `auth_header` configuration
and returns a dictionary of HTTP headers, resolving the credential
named by `env` through the supplied `CredentialProvider` (the
persona-scoped provider — persona `.env` first, process environment
fallback); omitting `credentials` falls back to the process
environment, preserving standalone behavior.

The system SHALL accept `auth_header_config` in two forms:

1. **Structured dict** — `{type: "bearer"|"api-key", env: <ref
   name>, header?: <custom header name>}`. `bearer` produces
   `{"Authorization": "Bearer <value>"}`; `api-key` produces
   `{<header or "X-API-Key">: <value>}`.
2. **Legacy flat string** — a persona's `auth_header_env` field that
   was already resolved to a literal token value is treated as a
   bearer token.

A ref that resolves to an EMPTY value (unset everywhere, or masked to
empty by the persona `.env`) MUST raise `KeyError` naming the ref;
`discover_tools` handles this as a source-skip per the "Missing auth
env var at discovery time skipped with warning" scenario.
`discover_tools` SHALL accept the persona's `CredentialProvider` and
pass it through to auth-header resolution for every source.

#### Scenario: Bearer token from provider

- **WHEN** `auth_header_config = {"type": "bearer", "env": "API_TOKEN"}`
- **AND** the persona-scoped provider resolves `API_TOKEN` to `"tok"`
- **THEN** `resolve_auth_header(...)` MUST return
  `{"Authorization": "Bearer tok"}`

#### Scenario: Persona .env credential is used for discovery

- **WHEN** a source's auth ref is defined only in the persona `.env`
  (not in the process environment)
- **AND** `discover_tools` is called with the persona's provider
- **THEN** the source's requests MUST carry the `.env`-resolved
  credential

#### Scenario: Empty resolution raises KeyError naming the ref

- **WHEN** `auth_header_config` references a ref that resolves to an
  empty value
- **THEN** `resolve_auth_header` MUST raise `KeyError` naming the ref
- **AND** `discover_tools` MUST skip the source with a warning

#### Scenario: Custom api-key header

- **WHEN** `auth_header_config = {"type": "api-key", "env":
  "API_KEY", "header": "X-Custom"}`
- **AND** the provider resolves `API_KEY` to `"k"`
- **THEN** the returned headers MUST equal `{"X-Custom": "k"}`
