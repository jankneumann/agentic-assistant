# persona-registry Specification (delta)

## MODIFIED Requirements

### Requirement: Persona Loading

The system SHALL load a persona by name into a typed `PersonaConfig`,
resolving `*_env` references in the YAML through the persona-scoped
`CredentialProvider` (persona `.env` values first, process environment
fallback — see the credential-provider capability) and loading optional
`prompt.md` and `memory.md` files from the persona directory. The
provider is built per persona at load time (or supplied by an injected
`credential_provider_factory`) and exposed as
`PersonaConfig.credentials` for downstream consumers.

#### Scenario: Load resolves env var references

- **WHEN** `persona.yaml` contains `database: { url_env: PERSONAL_DATABASE_URL }`
- **AND** the environment sets `PERSONAL_DATABASE_URL=postgresql://localhost/x`
- **THEN** `PersonaRegistry.load("personal").database_url` MUST equal
  `"postgresql://localhost/x"`

#### Scenario: Persona .env value takes precedence at load

- **WHEN** the persona directory's `.env` sets
  `PERSONAL_DATABASE_URL=postgresql://localhost/dotenv`
- **AND** the process environment sets a different value
- **THEN** the loaded `database_url` MUST equal
  `"postgresql://localhost/dotenv"`

#### Scenario: Missing env var resolves to empty string, not error

- **WHEN** `persona.yaml` references `url_env: UNDEFINED_VAR`
- **AND** `UNDEFINED_VAR` is not set in the environment
- **THEN** `load()` MUST return a `PersonaConfig` without raising
- **AND** the corresponding field MUST equal `""`

#### Scenario: Loaded result is cached

- **WHEN** `PersonaRegistry.load("personal")` is called twice
- **THEN** the second call MUST return the same object instance as the first

## ADDED Requirements

### Requirement: Guardrails Section Parsing

The persona registry SHALL parse and validate an optional
`guardrails:` section at load time into
`PersonaConfig.guardrails` (a typed `GuardrailConfig`, falsy when the
section is absent or empty). Validation failures (unknown keys,
unknown policy effects, malformed budget numbers) MUST raise a
`ValueError` naming the persona, the config path, and the offending
entry — the same actionable-error posture as the `models:` registry.

#### Scenario: Valid guardrails section is parsed

- **WHEN** `persona.yaml` declares
  `guardrails: {budgets: {model_call: {daily_usd: 5.0}}}`
- **THEN** the loaded `PersonaConfig.guardrails` MUST carry a
  model-call budget with `daily_usd == 5.0`

#### Scenario: Invalid guardrails section fails load actionably

- **WHEN** `persona.yaml` declares a policy with an unknown `effect`
- **THEN** `load()` MUST raise `ValueError`
- **AND** the message MUST contain `"guardrails"`

### Requirement: Extension Integrity Verification

The persona registry SHALL verify each private extension file against
an optional `manifest.yaml` in the persona's extensions directory
BEFORE executing it (i.e., before `spec.loader.exec_module()`). The
manifest maps extension filenames to SHA-256 digests
(`sha256:`-prefixed; bare hex accepted). Outcomes:

- **No manifest**: the extension loads, with a WARNING naming the
  `assistant persona hash-extensions` command (existing personas keep
  working).
- **Hash matches**: the extension loads silently.
- **Hash mismatch, file not listed, or manifest malformed**: the
  extension MUST NOT be executed and MUST be disabled with an ERROR
  log identifying the extension and the failure; sibling extensions
  continue loading (P10 failure isolation). A blocked private file
  MUST NOT fall back to a same-named public module.

#### Scenario: Verified extension loads silently

- **WHEN** the manifest lists the extension file with its current
  SHA-256
- **THEN** `load_extensions()` MUST return the extension
- **AND** no integrity warning MUST be logged

#### Scenario: Missing manifest loads with warning

- **WHEN** the extensions directory contains no `manifest.yaml`
- **THEN** `load_extensions()` MUST return the extension
- **AND** a WARNING naming the hash-generation command MUST be logged

#### Scenario: Mismatched extension is disabled without executing

- **WHEN** the extension file's content no longer matches its
  manifest digest
- **THEN** the file MUST NOT be executed
- **AND** an ERROR naming the extension MUST be logged
- **AND** the returned list MUST exclude that extension while
  including unaffected siblings

#### Scenario: Blocked private file does not fall back to a public module

- **WHEN** a private `gmail.py` fails verification
- **AND** a public `assistant.extensions.gmail` module exists
- **THEN** the returned list MUST NOT contain any `gmail` extension

#### Scenario: Malformed manifest blocks all private extensions

- **WHEN** `manifest.yaml` exists but is not a mapping with a
  `hashes:` section
- **THEN** every private extension in that directory MUST be disabled
  with an ERROR
