# test-privacy-boundary Specification

## Purpose
TBD - created by archiving change test-privacy-boundary. Update Purpose after archive.
## Requirements
### Requirement: Public test fixture root

Public test code under `tests/` SHALL load persona configuration exclusively
from the fixture root at `tests/fixtures/personas/`, and SHALL NOT read from
the submodule mount points under `personas/<name>/` at runtime, except for
`personas/_template/`.

#### Scenario: Public personas_dir fixture resolves to fixtures root

- **WHEN** a public test in `tests/` consumes the `personas_dir` pytest
  fixture
- **THEN** the fixture SHALL resolve to `<repo_root>/tests/fixtures/personas/`
- **AND** it SHALL NOT resolve to `<repo_root>/personas/`

#### Scenario: Public test suite passes without submodule content

- **WHEN** the private submodule `personas/personal/` is uninitialized,
  empty, or `git submodule deinit`-ed
- **AND** `uv run pytest tests/` is invoked from the repository root
- **THEN** the command SHALL exit with status 0
- **AND** no collected test SHALL require `personas/personal/persona.yaml`
  (or any file under `personas/<name>/` for any forbidden name) to exist

### Requirement: Two-layer collection-time and runtime boundary guard

The test suite SHALL enforce the privacy boundary at two layers, both
configured from a single deny-list module `tests/_privacy_guard_config.py`:

- **Layer 1 (collection-time substring scan)**: a
  `pytest_collection_modifyitems` hook in `tests/conftest.py` SHALL inspect
  the source text of every collected test file and every conftest under
  `tests/`, and SHALL fail the session if any inspected file contains a
  forbidden path substring outside the documented exclusion list.
- **Layer 2 (runtime filesystem guard)**: a pytest plugin SHALL patch
  `pathlib.Path.open`, `pathlib.Path.read_text`, `pathlib.Path.read_bytes`,
  `builtins.open`, `os.open`, and `subprocess.Popen.__init__` for the
  duration of test collection and execution, and SHALL raise a
  `pytest.UsageError` subclass when any of the file-opening entry points
  is called with a path that resolves under `personas/<name>/` for
  `<name>` in the forbidden-names list, or when a subprocess's argv
  contains a substring matching a forbidden path prefix, with allow-listed
  exceptions for paths under `tests/fixtures/` and `personas/_template/`.
- **Layer 2 self-probe**: at plugin-install time (`pytest_configure`), the
  plugin SHALL verify the patches are active by attempting a read of a
  canary forbidden path and asserting `_PrivacyBoundaryViolation` is
  raised. If the self-probe fails, the plugin SHALL fail the session via
  `pytest.UsageError` before any test body runs.

#### Scenario: Layer 1 rejects a literal forbidden path substring

- **WHEN** a public test file under `tests/test_*.py` or
  `tests/**/conftest.py` contains the literal substring
  `personas/personal/` or `personas/work/` in its source
- **AND** the file is not in the Layer 1 exclusion list
- **THEN** the pytest collection phase SHALL fail with an error identifying
  the violating file, the matched substring, and a remediation hint
- **AND** the session SHALL exit with a non-zero status before any test body
  executes

#### Scenario: Layer 1 allows template and fixture references

- **WHEN** a test file references `personas/_template/` or paths under
  `tests/fixtures/`
- **THEN** Layer 1 SHALL NOT raise an error for those references

#### Scenario: Layer 1 covers both personal and work persona names

- **WHEN** the guard is configured
- **THEN** the deny-list `FORBIDDEN_PATH_NAMES` SHALL include both
  `"personal"` and `"work"`
- **AND** Layer 1 SHALL reject substrings of the form `personas/personal/`
  or `personas/work/`, regardless of whether the corresponding submodule
  is currently populated

#### Scenario: Layer 2 rejects a runtime-constructed forbidden read

- **WHEN** any test code reads a file using `Path.open`, `Path.read_text`,
  `Path.read_bytes`, `builtins.open`, or `os.open`
- **AND** the resolved path is under `personas/<name>/` for `<name>` in
  `FORBIDDEN_PATH_NAMES`
- **AND** the resolved path is not under any prefix in
  `ALLOWED_READ_PREFIXES`
- **THEN** the call SHALL raise `_PrivacyBoundaryViolation`
- **AND** the test SHALL fail with a stack trace identifying the test file,
  the call site, and the resolved path

#### Scenario: Layer 2 rejects a forbidden subprocess argv

- **WHEN** any test code invokes `subprocess.Popen`, `subprocess.run`, or
  any wrapper that constructs a subprocess
- **AND** any element of the subprocess's `args` contains a substring of
  the form `personas/<name>/` for `<name>` in `FORBIDDEN_PATH_NAMES`
- **THEN** the call SHALL raise `_PrivacyBoundaryViolation` before the
  subprocess is spawned
- **AND** the failure message SHALL identify the test file, the
  subprocess call site, and the matched argv element

#### Scenario: Layer 2 self-probes after installation

- **WHEN** pytest's `pytest_configure` hook finishes installing the
  Layer 2 patches
- **THEN** the plugin SHALL attempt a canary read of a path under
  `personas/personal/` that is NOT allow-listed
- **AND** the attempt SHALL raise `_PrivacyBoundaryViolation`
- **AND** if the canary does NOT raise, the plugin SHALL fail the session
  via `pytest.UsageError("Layer 2 privacy guard failed to install")`
  before any test body runs

#### Scenario: Layer 2 permits allow-listed reads

- **WHEN** any test code reads a file under `tests/fixtures/` or
  `personas/_template/`
- **THEN** Layer 2 SHALL allow the read without raising

#### Scenario: Guard scope excludes its own implementation files

- **WHEN** Layer 1 inspects files under `tests/`
- **THEN** it SHALL skip `tests/_privacy_guard_config.py` and
  `tests/_privacy_guard_plugin.py`
- **AND** it SHALL skip files under `tests/fixtures/`

#### Scenario: Guard failure messages do not echo private payloads

- **WHEN** Layer 1 or Layer 2 emits a failure message
- **THEN** the message SHALL identify the violating file path and the
  matched deny-list entry by name
- **AND** the message SHALL NOT include the violating path's *file
  contents*, so failure logs do not become a private-data exfiltration
  vector

### Requirement: Self-contained persona-submodule test suite

Each persona submodule that ships tests SHALL contain a self-contained test
suite that runs without `assistant` being importable, and the
self-containment SHALL be verifiable by a fresh-venv proof.

#### Scenario: Submodule pyproject declares an isolated workspace

- **WHEN** `personas/personal/pyproject.toml` is read
- **THEN** it SHALL contain a `[tool.uv]` section declaring this directory
  as a non-package and SHALL NOT include the parent project as a workspace
  member
- **AND** `uv run pytest` invoked from inside `personas/personal/` SHALL NOT
  reuse the parent project's venv

#### Scenario: Submodule tests assert assistant import fails at runtime

- **WHEN** the submodule test suite runs in its isolated venv
- **THEN** the suite SHALL contain a positive runtime check that calls
  `importlib.import_module("assistant.core.persona")` — the qualified
  submodule path that is distinctive to this project and will not
  collide with the unrelated PyPI package named `assistant` — and
  asserts that the call raises `ImportError`
- **AND** the suite SHALL include a static check (grep or AST) that no
  test file under `personas/personal/tests/` contains the strings
  `import assistant`, `from assistant`, `from src.assistant`,
  `__import__("assistant")`, or `importlib.import_module("assistant")`
  outside the dedicated negative-import test

#### Scenario: Standalone-proof verification uses a fresh venv

- **WHEN** the standalone-proof step (task 3.6) runs
- **THEN** it SHALL create a freshly-provisioned virtual environment that
  does not have `assistant` installed
- **AND** it SHALL install only `pytest` and `pyyaml` (per
  `personas/personal/pyproject.toml`'s dev deps)
- **AND** it SHALL `cd` into `personas/personal/` before invoking pytest,
  so the submodule's own `pyproject.toml` is pytest's rootdir and the
  parent's `pytest_plugins` (privacy guard) are not loaded against
  submodule tests
- **AND** it SHALL invoke `pytest tests/` from inside the submodule using
  the fresh venv's interpreter
- **AND** the run SHALL exit with status 0
- **AND** `PYTHONPATH=/dev/null` SHALL NOT be relied upon as proof of
  isolation (it does not affect installed packages)

#### Scenario: Parent pyproject does not include submodule in a uv workspace

- **WHEN** `tests/test_workspace_hygiene.py` runs
- **THEN** it SHALL parse the parent repo's `pyproject.toml`
- **AND** it SHALL assert that either (a) no `[tool.uv.workspace]`
  section exists, or (b) if it does, `members` SHALL NOT contain any
  glob that matches `personas/personal/` or `personas/work/` (e.g.
  `personas/*`, `personas/**`)
- **AND** this guards against a future dev-ergonomics change
  accidentally drawing the submodule into the parent venv, which would
  defeat the self-containment invariant

#### Scenario: Submodule suite validates YAML shape

- **WHEN** the submodule test suite runs
- **THEN** it SHALL assert that `personas/personal/persona.yaml` contains
  the required top-level keys (`name`, `display_name`, `database`, `auth`,
  `harnesses`, `default_role`)
- **AND** it SHALL assert that `database.url_env` starts with `PERSONAL_`
- **AND** it SHALL assert that `graphiti.url_env` starts with `PERSONAL_`
  if the `graphiti` block is present (or assert the block's intentional
  absence per the persona's documented contract)
- **AND** it SHALL assert that every value of `auth.config.*_env` starts
  with `PERSONAL_`
- **AND** for each role override file under `personas/personal/roles/`, it
  SHALL assert that a base role of the same name exists in the parent
  repo's `roles/` directory, resolved via `parents[2] / "roles"`

#### Scenario: Standalone mode requires explicit opt-in

- **WHEN** the role-override-existence check runs and the parent `roles/`
  directory is not reachable from the submodule
- **AND** the env var `ALLOW_STANDALONE_SUBMODULE_SKIP=1` is NOT set
- **THEN** the test SHALL `pytest.fail` with a message naming the env var
  required to bypass the cross-repo check
- **WHEN** the env var IS set
- **THEN** the test SHALL `pytest.skip` with a clearly-flagged message

### Requirement: Replacement integration coverage for compose_system_prompt

The public test suite SHALL retain end-to-end coverage of
`compose_system_prompt` against a real persona+role load, using the public
fixture data, so that the composition pipeline is exercised end-to-end
without depending on the private submodule.

#### Scenario: Fixture-based composition test asserts on a fixture sentinel

- **WHEN** a public test in `tests/test_composition.py` calls
  `compose_system_prompt(persona, role)` against a persona+role loaded from
  `tests/fixtures/personas/`
- **THEN** the composed prompt SHALL contain a fixture-defined sentinel
  string that is unique to the fixture (e.g. `FIXTURE_PERSONA_SENTINEL`),
  not a string sourced from any real submodule's content
- **AND** the test SHALL assert on that sentinel, proving the composition
  pipeline traverses persona → role → output correctly

### Requirement: CI simplification and forward-compatible hygiene check

The `.github/workflows/ci.yml` workflow SHALL NOT contain any step that
populates, copies, or rsyncs content into `personas/<name>/`. A regression
guard SHALL prevent future workflows from silently re-introducing such a
dependency.

#### Scenario: CI omits the populate-personas step

- **WHEN** the CI workflow YAML is inspected
- **THEN** there SHALL NOT be any `run:` or `uses:` step whose effect is to
  write files into `personas/personal/` or `personas/work/`
- **AND** the `pytest` step SHALL succeed using only `tests/fixtures/personas/`
  as its persona data source

#### Scenario: Workflow-hygiene test rejects future leakage paths

- **WHEN** any file under `.github/workflows/` references `personas/personal/`
  or `personas/work/`
- **AND** the reference is not paired with an explicit
  copy-from-`tests/fixtures/` step
- **THEN** `tests/test_ci_workflow_hygiene.py` SHALL fail at collection or
  run time with a message identifying the workflow file and the violating
  reference

### Requirement: Documentation of the privacy boundary rule

The repository SHALL document the public-vs-private test rule in both
`CLAUDE.md` and `docs/gotchas.md`.

#### Scenario: CLAUDE.md records the convention

- **WHEN** `CLAUDE.md` is read
- **THEN** the "Conventions" section SHALL contain a bullet stating that
  public tests use fixtures only and that persona-specific tests live in
  the persona's private submodule and are self-contained

#### Scenario: docs/gotchas.md records the failure mode

- **WHEN** `docs/gotchas.md` is read
- **THEN** a new gotcha entry SHALL describe the private-content leakage
  failure mode (symptom: CI passes locally but private content appears in
  public test code or assertions; root cause: `personas_dir` was pointed
  at the real submodule, OR a runtime path was constructed via path-join
  to bypass substring matching; fix: repoint to fixtures + rely on the
  two-layer guard; prevention: the runtime FS guard + the workflow-hygiene
  test catch both classes of regression)
- **AND** a separate entry SHALL document the
  `ALLOW_STANDALONE_SUBMODULE_SKIP=1` opt-in for submodule maintainers
  running tests outside a parent checkout

