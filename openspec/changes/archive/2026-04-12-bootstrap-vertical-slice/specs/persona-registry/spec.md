# Spec Delta: persona-registry

## ADDED Requirements

### Requirement: Persona Discovery

The system SHALL discover personas as subdirectories of a configured personas
root that contain a `persona.yaml` file, excluding directories whose name
starts with an underscore.

#### Scenario: Populated submodule is discovered

- **WHEN** `personas/personal/persona.yaml` exists and is a regular file
- **THEN** `PersonaRegistry.discover()` MUST include `"personal"` in its
  returned list
- **AND** the returned list MUST be sorted alphabetically

#### Scenario: Template directory is excluded

- **WHEN** `personas/_template/persona.yaml` exists
- **THEN** `PersonaRegistry.discover()` MUST NOT include `"_template"`

#### Scenario: Uninitialized submodule is skipped

- **WHEN** `personas/work/` exists as a directory but contains no
  `persona.yaml` (uninitialized submodule)
- **THEN** `PersonaRegistry.discover()` MUST NOT include `"work"`

### Requirement: Persona Loading

The system SHALL load a persona by name into a typed `PersonaConfig`,
resolving `*_env` references in the YAML against the process environment and
loading optional `prompt.md` and `memory.md` files from the persona directory.

#### Scenario: Load resolves env var references

- **WHEN** `persona.yaml` contains `database: { url_env: PERSONAL_DATABASE_URL }`
- **AND** the environment sets `PERSONAL_DATABASE_URL=postgresql://localhost/x`
- **THEN** `PersonaRegistry.load("personal").database_url` MUST equal
  `"postgresql://localhost/x"`

#### Scenario: Missing env var resolves to empty string, not error

- **WHEN** `persona.yaml` references `url_env: UNDEFINED_VAR`
- **AND** `UNDEFINED_VAR` is not set in the environment
- **THEN** `load()` MUST return a `PersonaConfig` without raising
- **AND** the corresponding field MUST equal `""`

#### Scenario: Loaded result is cached

- **WHEN** `PersonaRegistry.load("personal")` is called twice
- **THEN** the second call MUST return the same object instance as the first

### Requirement: Persona Prompt and Memory Inclusion

The loader SHALL read optional `prompt.md` and `memory.md` files from the
persona directory into `PersonaConfig.prompt_augmentation` and
`PersonaConfig.memory_content` respectively when those files exist.

#### Scenario: prompt.md is loaded

- **WHEN** `personas/personal/prompt.md` contains `"## Personal Context..."`
- **THEN** the loaded `PersonaConfig.prompt_augmentation` MUST contain that
  string

#### Scenario: memory.md is optional

- **WHEN** `personas/personal/memory.md` does not exist
- **THEN** `load()` MUST succeed
- **AND** `PersonaConfig.memory_content` MUST equal `""`

### Requirement: Helpful Error on Uninitialized Submodule

The loader SHALL raise a `ValueError` when a persona is requested whose
directory is missing `persona.yaml`; the error message MUST include the list
of available personas and a hint showing the `git submodule update --init`
command.

#### Scenario: Error message lists alternatives

- **WHEN** `PersonaRegistry.load("work")` is called and `personas/work/` does
  not contain `persona.yaml`
- **THEN** `ValueError` MUST be raised
- **AND** the message MUST contain the substring `"Available:"`
- **AND** the message MUST contain the substring `"git submodule update --init"`

### Requirement: Extension Loader Fallback Order

The persona registry SHALL provide a `load_extensions()` method that, for each
extension in `PersonaConfig.extensions`, attempts to load from
`personas/<persona>/extensions/<module>.py` first (private override) and falls
back to `src/assistant/extensions/<module>.py` (public generic) if the private
file does not exist.

#### Scenario: Private extension takes precedence

- **WHEN** both `personas/personal/extensions/gmail.py` and
  `src/assistant/extensions/gmail.py` exist and define `create_extension`
- **THEN** `load_extensions()` MUST return the instance produced by the
  private `create_extension`

#### Scenario: Public fallback used when no private override

- **WHEN** `personas/personal/extensions/gmail.py` does not exist
- **AND** `src/assistant/extensions/gmail.py` defines `create_extension`
- **THEN** `load_extensions()` MUST return the instance produced by the
  public `create_extension`

#### Scenario: Missing module logs warning and continues

- **WHEN** neither a private nor a public module for the named extension
  exists
- **THEN** `load_extensions()` MUST NOT raise
- **AND** the returned list MUST exclude that extension
