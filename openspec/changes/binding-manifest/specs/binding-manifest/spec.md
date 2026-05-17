# binding-manifest — spec delta

## ADDED Requirements

### Requirement: BindingManifest Schema

The system SHALL define a Pydantic `BindingManifest` model that loads
and validates a `binding.yaml` file with a `binding:` top-level key
and `manifest_version`, `persona`, `providers`, and
`compatibility_groups` fields.

#### Scenario: Valid manifest parses

- **WHEN** `BindingManifest.load(path)` is called with a YAML file
  containing valid `manifest_version: 1`, `persona`, `providers`, and
  `compatibility_groups` fields
- **THEN** the call MUST return a `BindingManifest` instance
- **AND** every named provider MUST be accessible as a typed attribute
- **AND** every compatibility group MUST be accessible as a list
  attribute

#### Scenario: Unknown manifest version rejected

- **WHEN** `BindingManifest.load(path)` is called with
  `manifest_version: 99`
- **THEN** the call MUST raise `BindingSchemaError` naming the
  unsupported version

#### Scenario: Missing required provider rejected

- **WHEN** `BindingManifest.load(path)` is called with a YAML file
  missing the required `providers.model` key
- **THEN** the call MUST raise `BindingSchemaError` naming the missing
  provider slot

### Requirement: Provider Binding Slots

The system SHALL define a fixed enumeration of provider binding slots
(`model`, `harnesses`, `memory`, `identity`, `capability_registry`,
`observability`, `sandbox`) such that each binding manifest declares
exactly one provider for each slot, except `harnesses` which accepts
a list with at least one entry marked `default: true`.

#### Scenario: Multiple harnesses with one default

- **WHEN** a manifest declares two harnesses in `providers.harnesses`,
  one with `default: true`
- **THEN** the parsed manifest MUST expose both harnesses
- **AND** `manifest.providers.harnesses.default` MUST return the
  default-marked harness

#### Scenario: No default harness rejected

- **WHEN** a manifest declares two harnesses with neither marked
  `default: true`
- **THEN** `BindingManifest.load(path)` MUST raise `BindingSchemaError`
  naming the missing-default failure

### Requirement: Compatibility Group Declarations

The system SHALL parse `compatibility_groups` entries each containing
`name` and `requires` fields, where `requires` is a mapping from
provider slot name to required capability identifier.

#### Scenario: Compatibility group parses

- **WHEN** a manifest declares a compatibility group named
  `interrupt_resume` with `requires` mapping
  `{harness: interrupt_resume, session: checkpoint_mid_turn,
  memory: replay_safe}`
- **THEN** `manifest.compatibility_groups[0].name` MUST equal
  `"interrupt_resume"`
- **AND** `manifest.compatibility_groups[0].requires["harness"]` MUST
  equal `"interrupt_resume"`

### Requirement: Environment Variable Interpolation

The system SHALL interpolate environment variables of the form
`${NAME}` in string values within the manifest, evaluating them
against the process environment at load time.

#### Scenario: Environment variable interpolated

- **GIVEN** the environment variable `ASSISTANT_DATABASE_URL` is set
  to `postgresql://localhost/personal`
- **WHEN** a manifest with `providers.memory.connection:
  ${ASSISTANT_DATABASE_URL}` is loaded
- **THEN** `manifest.providers.memory.connection` MUST equal
  `"postgresql://localhost/personal"`

#### Scenario: Missing environment variable rejected

- **GIVEN** the environment variable `ASSISTANT_VAULT_MOUNT` is unset
- **WHEN** a manifest with `providers.identity.mount:
  ${ASSISTANT_VAULT_MOUNT}` is loaded
- **THEN** `BindingManifest.load(path)` MUST raise
  `BindingSchemaError` naming the unset variable

### Requirement: Legacy Synthesis

The system SHALL synthesize a default `BindingManifest` from the
legacy `persona.yaml` `harnesses.*` keys plus environment-supplied
connection strings when no `binding.yaml` file exists, with a
deprecation warning naming the persona.

#### Scenario: Legacy persona produces a default manifest

- **GIVEN** a persona directory containing `persona.yaml` with
  `harnesses.deep_agents.enabled: true` but no `binding.yaml`
- **WHEN** `BindingManifest.synthesize_from_legacy(persona_config)`
  is called
- **THEN** the call MUST return a `BindingManifest` with
  `providers.harnesses` containing a `deep_agents` entry marked
  `default: true`
- **AND** a `DeprecationWarning` MUST be emitted naming the persona
  and recommending an explicit `binding.yaml`

### Requirement: Validator Loud-Failure

The system SHALL provide a `BindingValidator.validate(manifest,
role_registry, provider_registry)` method that raises
`BindingValidationError` containing a list of all failures (provider
not found, capability not supported, compatibility group unsatisfied,
role required capability unsatisfied) rather than stopping at the
first failure.

#### Scenario: Multiple failures collected

- **WHEN** a manifest declares an unknown provider AND a role
  requiring an unsatisfiable capability are both validated
- **THEN** `BindingValidator.validate` MUST raise
  `BindingValidationError`
- **AND** the raised error MUST contain at least two failure entries
- **AND** each failure entry MUST name the specific failing
  component (provider name, capability identifier, role name)

#### Scenario: Valid manifest passes

- **WHEN** a manifest declares only known providers, only supported
  capabilities, and all compatibility groups are satisfiable
- **AND** all roles' `requires_capabilities` are satisfied
- **THEN** `BindingValidator.validate` MUST return without raising

### Requirement: PersonaRegistry Integration

The system SHALL extend `PersonaRegistry.load(name)` to load
`binding.yaml` (or synthesize from legacy), validate it, and attach
the resolved `BindingManifest` to the returned `PersonaConfig` as a
`binding` attribute.

#### Scenario: PersonaConfig exposes resolved binding

- **WHEN** `PersonaRegistry.load("personal")` is called with a
  persona directory containing a valid `binding.yaml`
- **THEN** the returned `PersonaConfig` MUST have a `binding`
  attribute
- **AND** `persona.binding` MUST be a `BindingManifest` instance
- **AND** `persona.binding.persona` MUST equal `"personal"`

#### Scenario: Invalid binding fails at load time

- **WHEN** `PersonaRegistry.load("personal")` is called with a
  persona directory containing an invalid `binding.yaml`
- **THEN** the call MUST raise `BindingValidationError`
- **AND** the REPL MUST NOT start

### Requirement: CLI Binding Subcommand

The system SHALL provide an `assistant binding` subcommand with three
verbs: `check` (run the validator, exit 0 on success / non-zero on
failure), `show` (pretty-print the resolved manifest), and `explain
<capability>` (name the providing implementation for a capability
identifier).

#### Scenario: Check succeeds on valid persona

- **WHEN** `assistant binding check -p personal` is invoked against
  a persona with a valid binding
- **THEN** the command MUST exit with code 0
- **AND** stdout MUST contain a success message naming the validated
  persona

#### Scenario: Check fails with formatted error

- **WHEN** `assistant binding check -p personal` is invoked against
  a persona with an invalid binding
- **THEN** the command MUST exit with non-zero code
- **AND** stderr MUST contain a list of validation failures, one per
  line

## MODIFIED Requirements

### Requirement: MemoryManager Methods Persona-Agnostic

The `MemoryManager` interface SHALL NOT accept a `persona` parameter
on any method. The instance is persona-bound at construction via the
`session_factory` (which is itself persona-scoped per the binding
manifest).

This MODIFIES the prior memory-policy contract that accepted
`persona: str` on `get_context`, `store_fact`, `store_interaction`,
`update_preference`, `list_facts`, and similar methods.

#### Scenario: get_context signature

- **WHEN** the caller invokes `manager.get_context(role="researcher",
  limit=50)`
- **THEN** the call MUST return the active and semantic context
  sections for the bound persona's `researcher` role
- **AND** no `persona` parameter MUST appear in the signature

#### Scenario: store_fact signature

- **WHEN** the caller invokes `manager.store_fact(key="preferred_lang",
  value="en")`
- **THEN** the call MUST persist the fact for the bound persona
- **AND** no `persona` parameter MUST appear in the signature

#### Scenario: Persona name available for observability

- **WHEN** a memory operation traces a span
- **THEN** the span attribute `assistant.persona` MUST equal the bound
  persona's name
- **AND** the persona name MUST be read from the MemoryManager
  instance's internal `_persona_name`, NOT from a caller-supplied
  parameter
