# persona-registry Specification

## Purpose
Governs persona discovery and loading: finding personas as subdirectories
of the configured personas root (mounted private submodules), loading their
configuration, including persona prompt and memory content, producing a
helpful error when a submodule is uninitialized, and the extension-loader
fallback order. It exists because a persona is the execution boundary —
database, auth, tools, and identity live in private config repos that the
public code must locate and load without embedding any private content.
Consumers are the CLI, the web server, prompt composition, and the
delegation spawner.
## Requirements
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

### Requirement: Extension Initialization and Shutdown Lifecycle

The persona registry SHALL drive the optional extension lifecycle
hooks around `load_extensions()`:

- **Initialization**: for each extension instance produced during
  loading, the registry SHALL call the extension's `initialize()`
  hook (when present and callable) in `PersonaConfig.extensions`
  declaration order, immediately post-load. The registry SHALL await
  the hook's result only when it is awaitable, tolerating synchronous
  hooks on out-of-tree extensions. An extension without the hook is
  loaded as before.
- **Failure isolation**: when `initialize()` raises, the registry
  SHALL log a WARNING identifying the extension and the error,
  attempt a best-effort `shutdown()` of the failed instance (errors
  swallowed), exclude that extension from the returned list, and
  continue loading the remaining extensions. Persona load MUST NOT
  fail because one extension failed to initialize.
- **Async variant**: the registry SHALL provide
  `load_extensions_async(config)` for callers already running inside
  an event loop. The synchronous `load_extensions(config)` SHALL
  execute the identical load+initialize pipeline via `asyncio.run()`
  when no event loop is running, and SHALL raise a `RuntimeError`
  naming `load_extensions_async` when called while a loop is running.
- **Shutdown registration**: extensions returned by a load SHALL be
  tracked as active. The registry SHALL register a process-exit
  (`atexit`) handler at most once per registry instance, and SHALL
  provide an explicit async `shutdown_extensions()` that calls each
  active extension's `shutdown()` hook (when present) in reverse
  activation order, swallowing and WARNING-logging per-extension
  errors. `shutdown_extensions()` MUST be idempotent — a second call
  after a completed shutdown is a no-op.

#### Scenario: initialize called post-load in declaration order

- **WHEN** `load_extensions()` runs for a persona declaring
  extensions `a` then `b`, both defining `initialize()`
- **THEN** `a.initialize()` MUST be awaited before `b.initialize()`
- **AND** both instances MUST appear in the returned list

#### Scenario: failing initialize disables only that extension

- **WHEN** extension `a`'s `initialize()` raises and sibling `b`'s
  succeeds
- **THEN** `load_extensions()` MUST NOT raise
- **AND** the returned list MUST contain `b` but not `a`
- **AND** a WARNING naming `a` MUST be logged

#### Scenario: extension without hooks loads unchanged

- **WHEN** a loaded extension defines no lifecycle hooks
- **THEN** `load_extensions()` MUST return it without warnings about
  missing hooks

#### Scenario: sync load_extensions rejects a running event loop

- **WHEN** `load_extensions()` is called from a coroutine running in
  an event loop
- **THEN** a `RuntimeError` MUST be raised
- **AND** the message MUST name `load_extensions_async`

#### Scenario: shutdown_extensions runs hooks in reverse order and is idempotent

- **WHEN** extensions `a` then `b` were activated and
  `await shutdown_extensions()` is called
- **THEN** `b.shutdown()` MUST be awaited before `a.shutdown()`
- **AND** a second `await shutdown_extensions()` MUST complete
  without calling any hook again

#### Scenario: shutdown hook failure is contained

- **WHEN** `b.shutdown()` raises during `shutdown_extensions()`
- **THEN** `a.shutdown()` MUST still be awaited
- **AND** a WARNING naming `b` MUST be logged

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

