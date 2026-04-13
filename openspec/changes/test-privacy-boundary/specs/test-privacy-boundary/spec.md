# test-privacy-boundary

## ADDED Requirements

### Requirement: Public test fixture root

Public test code under `tests/` SHALL load persona configuration exclusively
from the fixture root at `tests/fixtures/personas/`, and SHALL NOT read from
the submodule mount points under `personas/<name>/` at runtime.

#### Scenario: Public personas_dir fixture resolves to fixtures root

- **WHEN** a public test in `tests/` consumes the `personas_dir` pytest fixture
- **THEN** the fixture SHALL resolve to `<repo_root>/tests/fixtures/personas/`
- **AND** it SHALL NOT resolve to `<repo_root>/personas/`

#### Scenario: Public test suite passes without submodule content

- **WHEN** the private submodule `personas/personal/` is uninitialized, empty,
  or git-removed
- **AND** `uv run pytest tests/` is invoked from the repository root
- **THEN** the command SHALL exit with status 0
- **AND** no collected test SHALL require `personas/personal/persona.yaml` (or
  any file under `personas/<name>/` for any persona name) to exist

### Requirement: Collection-time boundary guard

A `pytest_collection_modifyitems` hook registered in `tests/conftest.py` SHALL
inspect the source text of every collected public test file and fail the
session if the file references private persona paths or known private-content
strings.

#### Scenario: Guard rejects a forbidden path reference

- **WHEN** a public test file under `tests/` (excluding `tests/fixtures/`)
  contains the literal substring `personas/personal/` or `personas/work/` in
  its source
- **THEN** the pytest collection phase SHALL emit an error identifying the
  violating file and the matched substring
- **AND** the session SHALL exit with a non-zero status before any test body
  executes

#### Scenario: Guard rejects a private-content string

- **WHEN** a public test file under `tests/` (excluding `tests/fixtures/`)
  contains any string in the configured private-content deny-list (e.g.
  `"Personal Persona Context"`, `"Personal Context Additions"`)
- **THEN** the collection phase SHALL fail with a message naming the leaked
  string and the violating file
- **AND** remediation guidance SHALL direct the author to either move the test
  into the persona's submodule suite or rewrite it against fixture values

#### Scenario: Guard allows template and fixture references

- **WHEN** a test file references `personas/_template/` or paths under
  `tests/fixtures/`
- **THEN** the collection guard SHALL NOT raise an error for those references

#### Scenario: Guard covers both personal and work personas

- **WHEN** the guard is configured
- **THEN** its deny-list SHALL include both `personas/personal/` and
  `personas/work/` path prefixes
- **AND** the guard SHALL reject references to either, regardless of whether
  the corresponding submodule is currently populated

### Requirement: Self-contained persona-submodule test suite

Each persona submodule that ships tests SHALL contain a self-contained test
suite that runs without importing any symbol from the main repo's
`src/assistant/` package or the public `tests/` directory.

#### Scenario: Submodule tests run standalone

- **WHEN** pytest is invoked from inside `personas/personal/` with that
  submodule's dev dependencies installed (e.g. `uv run pytest` after
  `uv sync` inside the submodule)
- **THEN** the test suite SHALL collect and execute successfully without the
  parent repo's `src/assistant/` package being importable
- **AND** no test in `personas/personal/tests/` SHALL contain the import
  statement `import assistant` or `from assistant` or `from src.assistant`

#### Scenario: Submodule suite validates YAML shape

- **WHEN** the submodule test suite runs
- **THEN** it SHALL assert that `personas/personal/persona.yaml` contains the
  required top-level keys (`name`, `display_name`, `database`, `auth`,
  `harnesses`, `default_role`)
- **AND** it SHALL assert that `database.url_env`, `graphiti.url_env`, and all
  `auth.config.*_env` values follow the `PERSONAL_*` prefix convention
- **AND** for each role override file under `personas/personal/roles/`, it
  SHALL assert that a base role of the same name exists in the parent repo's
  `roles/` directory (the parent `roles/` path is resolved relative to the
  submodule mount via `../..`)

### Requirement: CI simplification

The `.github/workflows/ci.yml` workflow SHALL NOT contain any step that
populates, copies, or rsyncs content into `personas/<name>/`.

#### Scenario: CI omits the populate-personas step

- **WHEN** the CI workflow YAML is inspected
- **THEN** there SHALL NOT be any `run:` or `uses:` step whose effect is to
  write files into `personas/personal/` or `personas/work/`
- **AND** the `pytest` step SHALL succeed using only `tests/fixtures/personas/`
  as its persona data source

### Requirement: Documentation of the privacy boundary rule

The repository SHALL document the public-vs-private test rule in both
`CLAUDE.md` and `docs/gotchas.md`.

#### Scenario: CLAUDE.md records the convention

- **WHEN** `CLAUDE.md` is read
- **THEN** the "Conventions" section SHALL contain a bullet stating that
  public tests use fixtures only and that persona-specific tests live in the
  persona's private submodule and are self-contained

#### Scenario: docs/gotchas.md records the failure mode

- **WHEN** `docs/gotchas.md` is read
- **THEN** a new gotcha entry SHALL describe the private-content leakage
  failure mode (symptom: CI passes locally but private strings appear in
  public test assertions; root cause: `personas_dir` was pointed at the real
  submodule; fix: repoint to fixtures + rely on the conftest guard;
  prevention: let the collection guard catch new violations)
