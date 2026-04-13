# test-privacy-boundary

## MODIFIED Requirements

### Requirement: Public test fixture root

Public test code under `tests/` SHALL load persona configuration
exclusively from the fixture root at `tests/fixtures/personas/`, and
SHALL NOT read from the submodule mount points under `personas/<name>/`
at runtime, except for `personas/_template/`. In-process consumers of
the persona configuration (such as the CLI `assistant -p personal`
invoked inside public tests) SHALL honor the fixture repoint via the
`ASSISTANT_PERSONAS_DIR` environment variable.

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
  (or any file under `personas/<name>/` for any forbidden name) to
  exist

#### Scenario: Public conftest sets ASSISTANT_PERSONAS_DIR at session start

- **WHEN** `tests/conftest.py` is loaded by pytest at session start
- **THEN** it SHALL call `os.environ.setdefault("ASSISTANT_PERSONAS_DIR", ...)`
  with a value pointing at `<repo_root>/tests/fixtures/personas/`
- **AND** the use of `setdefault` SHALL respect any operator-set
  override (e.g. a developer exporting a custom fixtures path before
  running pytest)

#### Scenario: PersonaRegistry and RoleRegistry honor ASSISTANT_PERSONAS_DIR

- **WHEN** `PersonaRegistry()` or `RoleRegistry()` is constructed
  without an explicit `personas_dir` argument
- **AND** the environment variable `ASSISTANT_PERSONAS_DIR` is set
- **THEN** the resulting `personas_dir` attribute SHALL equal
  `Path(os.environ["ASSISTANT_PERSONAS_DIR"])`
- **WHEN** an explicit `personas_dir` argument is supplied
- **THEN** the explicit argument SHALL override the environment variable
- **WHEN** the environment variable is unset AND no explicit argument is
  supplied
- **THEN** the default SHALL be `Path("personas")` (preserving
  backward-compatibility for production callers)

#### Scenario: CI workflow declares ASSISTANT_PERSONAS_DIR at job level

- **WHEN** the `.github/workflows/ci.yml` job runs
- **THEN** `ASSISTANT_PERSONAS_DIR` SHALL be declared under the job's
  `env:` block with value `tests/fixtures/personas`
- **AND** this declaration SHALL apply to every step in the job
  (including Ruff, Mypy, and Pytest), so that any future static-analysis
  step that inadvertently loads persona configs sees the fixture root
  and not an empty submodule mount

### Requirement: Two-layer collection-time and runtime boundary guard

The test suite SHALL enforce the privacy boundary at two layers, both
configured from a single deny-list module
`tests/_privacy_guard_config.py`:

- **Layer 1 (collection-time substring scan)**: a
  `pytest_collection_modifyitems` hook in `tests/conftest.py` SHALL
  inspect the source text of every collected test file and every
  conftest under `tests/`, and SHALL fail the session if any inspected
  file contains a forbidden path substring outside the documented
  exclusion list.
- **Layer 2 (runtime filesystem guard)**: a pytest plugin SHALL patch
  `pathlib.Path.open`, `pathlib.Path.read_text`, `pathlib.Path.read_bytes`,
  `builtins.open`, `os.open`, and `subprocess.Popen.__init__` for the
  duration of test collection and execution, and SHALL raise a
  `pytest.UsageError` subclass when any of the file-opening entry points
  is called with a path that resolves under `personas/<name>/` for
  `<name>` in the forbidden-names list, or when a subprocess's **argv,
  `executable=`, or `cwd=`** references such a path, with allow-listed
  exceptions for paths under `tests/fixtures/` and
  `personas/_template/`.
- **Layer 2 self-probe**: at plugin-install time
  (`pytest_configure`), the plugin SHALL verify the patches are active
  by attempting a read of a canary forbidden path and asserting
  `_PrivacyBoundaryViolation` is raised. If the self-probe fails, the
  plugin SHALL fail the session via `pytest.UsageError` before any test
  body runs.

#### Scenario: Layer 1 rejects a literal forbidden path substring

- **WHEN** a public test file under `tests/test_*.py` or
  `tests/**/conftest.py` contains the literal substring
  `personas/personal/` or `personas/work/` in its source
- **AND** the file is not in the Layer 1 exclusion list
- **THEN** the pytest collection phase SHALL fail with an error
  identifying the violating file, the matched substring, and a
  remediation hint
- **AND** the session SHALL exit with a non-zero status before any test
  body executes

#### Scenario: Layer 1 allows template and fixture references

- **WHEN** a test file references `personas/_template/` or paths under
  `tests/fixtures/`
- **THEN** Layer 1 SHALL NOT raise an error for those references

#### Scenario: Layer 1 covers both personal and work persona names

- **WHEN** the guard is configured
- **THEN** the deny-list `FORBIDDEN_PATH_NAMES` SHALL include both
  `"personal"` and `"work"`
- **AND** Layer 1 SHALL reject substrings of the form
  `personas/personal/` or `personas/work/`, regardless of whether the
  corresponding submodule is currently populated

#### Scenario: Layer 2 rejects a runtime-constructed forbidden read

- **WHEN** any test code reads a file using `Path.open`,
  `Path.read_text`, `Path.read_bytes`, `builtins.open`, or `os.open`
- **AND** the resolved path is under `personas/<name>/` for `<name>` in
  `FORBIDDEN_PATH_NAMES`
- **AND** the resolved path is not under any prefix in
  `ALLOWED_READ_PREFIXES`
- **THEN** the call SHALL raise `_PrivacyBoundaryViolation`
- **AND** the test SHALL fail with a stack trace identifying the test
  file, the call site, and the resolved path

#### Scenario: Layer 2 rejects a forbidden subprocess argv

- **WHEN** any test code invokes `subprocess.Popen`, `subprocess.run`,
  or any wrapper that constructs a subprocess
- **AND** any element of the subprocess's `args` contains a substring of
  the form `personas/<name>/` for `<name>` in `FORBIDDEN_PATH_NAMES`,
  OR references the bare directory `personas/<name>` at a path-component
  boundary (e.g. `git -C personas/personal log`)
- **THEN** the call SHALL raise `_PrivacyBoundaryViolation` before the
  subprocess is spawned
- **AND** the failure message SHALL identify the test file, the
  subprocess call site, and the matched argv element

#### Scenario: Layer 2 rejects forbidden subprocess kwargs

- **WHEN** any test code invokes `subprocess.Popen` or
  `subprocess.run` with an `executable=<path>` or `cwd=<path>` kwarg
- **AND** the path value contains a forbidden substring or bare
  directory reference (same match rule as the argv scenario)
- **THEN** the call SHALL raise `_PrivacyBoundaryViolation` before the
  subprocess is spawned

#### Scenario: Layer 2 self-probes after installation

- **WHEN** pytest's `pytest_configure` hook finishes installing the
  Layer 2 patches
- **THEN** the plugin SHALL attempt a canary read of a path under
  `personas/personal/` that is NOT allow-listed
- **AND** the attempt SHALL raise `_PrivacyBoundaryViolation`
- **AND** if the canary does NOT raise, the plugin SHALL fail the
  session via `pytest.UsageError("Layer 2 privacy guard failed to
  install")` before any test body runs

#### Scenario: Layer 2 permits allow-listed reads

- **WHEN** any test code reads a file under `tests/fixtures/` or
  `personas/_template/`
- **THEN** Layer 2 SHALL allow the read without raising

#### Scenario: Guard scope excludes its own implementation files

- **WHEN** Layer 1 inspects files under `tests/`
- **THEN** it SHALL skip the **four** files that reference forbidden
  path names as data:
  - `tests/_privacy_guard_config.py` (the deny-list constants)
  - `tests/_privacy_guard_plugin.py` (the Layer 2 runtime guard
    implementation)
  - `tests/test_ci_workflow_hygiene.py` (scans workflow YAML for
    forbidden references)
  - `tests/test_workspace_hygiene.py` (scans parent `pyproject.toml`
    for `personas/*` workspace members)
- **AND** it SHALL skip files under `tests/fixtures/` and
  `tests/_helpers/`
- **AND** the hygiene test files SHALL construct their forbidden
  needles dynamically from `FORBIDDEN_PATH_NAMES` rather than embedding
  the substring as a source literal — this is belt-and-suspenders with
  the exclusion list so accidental literal-addition does not
  immediately self-trip

#### Scenario: Guard failure messages do not echo private payloads

- **WHEN** Layer 1 or Layer 2 emits a failure message
- **THEN** the message SHALL identify the violating file path and the
  matched deny-list entry by name
- **AND** the message SHALL NOT include the violating path's *file
  contents*, so failure logs do not become a private-data exfiltration
  vector

### Requirement: Self-contained persona-submodule test suite

Each persona submodule that ships tests SHALL contain a self-contained
test suite that runs without `assistant` being importable, and the
self-containment SHALL be verifiable by a fresh-venv proof.

#### Scenario: Submodule pyproject declares an isolated workspace

- **WHEN** `personas/personal/pyproject.toml` is read
- **THEN** it SHALL contain a `[tool.uv]` section declaring this
  directory as a non-package and SHALL NOT include the parent project
  as a workspace member
- **AND** `uv run pytest` invoked from inside `personas/personal/`
  SHALL NOT reuse the parent project's venv

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

- **WHEN** the standalone-proof step runs
- **THEN** it SHALL create a freshly-provisioned virtual environment
  that does not have `assistant` installed
- **AND** it SHALL install only `pytest` and `pyyaml` (per
  `personas/personal/pyproject.toml`'s dev deps)
- **AND** it SHALL `cd` into `personas/personal/` before invoking
  pytest, so the submodule's own `pyproject.toml` is pytest's rootdir
  and the parent's `pytest_plugins` (privacy guard) are not loaded
  against submodule tests
- **AND** it SHALL invoke `pytest tests/` from inside the submodule
  using the fresh venv's interpreter
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
- **THEN** it SHALL assert that `personas/personal/persona.yaml`
  contains the required top-level keys (`name`, `display_name`,
  `database`, `auth`, `harnesses`, `default_role`)
- **AND** it SHALL assert that `database.url_env` starts with
  `PERSONAL_`
- **AND** it SHALL assert that `graphiti.url_env` starts with
  `PERSONAL_` if the `graphiti` block is present (or assert the
  block's intentional absence per the persona's documented contract)
- **AND** it SHALL assert that every value of `auth.config.*_env`
  starts with `PERSONAL_`
- **AND** for each role override file under `personas/personal/roles/`,
  it SHALL assert that a base role of the same name exists in the
  parent repo's `roles/` directory, resolved **two levels above the
  persona directory** (the exact `parents[N]` count depends on which
  file performs the resolution — the conftest uses `parents[3]`
  because it lives one level deeper than the test files that use
  `parents[2]`; both land at the parent-repo root)

#### Scenario: Standalone mode requires explicit opt-in

- **WHEN** the role-override-existence check runs and the parent
  `roles/` directory is not reachable from the submodule
- **AND** the env var `ALLOW_STANDALONE_SUBMODULE_SKIP=1` is NOT set
- **THEN** the test SHALL `pytest.fail` with a message naming the env
  var required to bypass the cross-repo check
- **WHEN** the env var IS set
- **THEN** the test SHALL `pytest.skip` with a clearly-flagged message

## ADDED Requirements

### Requirement: Atomic dual-commit push wrapper

A reusable shell script `scripts/push-with-submodule.sh` SHALL handle
the two-commit push sequence (submodule commit → submodule push →
parent gitlink commit → parent push) required by the submodule-
consuming architecture, with a documented exit-code contract so that a
downstream dispatcher can distinguish operator-handoff scenarios from
benign push failures.

#### Scenario: Script supports submodule-only and parent-only modes

- **WHEN** `scripts/push-with-submodule.sh --submodule-only` is invoked
- **THEN** it SHALL `cd` into `personas/personal/`, push the current
  branch to the private remote, and print the pushed SHA on success
- **WHEN** `scripts/push-with-submodule.sh --parent-only` is invoked
- **THEN** it SHALL verify the parent branch is rebased onto
  `origin/main`, `git add personas/personal` to stage the gitlink,
  commit the SHA bump, and push the parent branch

#### Scenario: Parent push reserves exit code 47 for dangling-SHA cases

- **WHEN** `--parent-only` push fails
- **AND** the submodule's current HEAD is confirmed reachable on the
  submodule remote (via
  `git -C personas/personal branch -r --contains HEAD`)
- **THEN** the script SHALL exit with code 47
- **AND** the stderr SHALL include the submodule SHA, recovery
  commands, and a clear explanation of the dangling-SHA scenario
- **WHEN** `--parent-only` push fails AND the submodule SHA is NOT yet
  on the submodule remote
- **THEN** the script SHALL exit with code 1 (benign failure) and
  instruct the operator to run `--submodule-only` first

#### Scenario: Script is idempotent within a mode

- **WHEN** `--parent-only` is re-invoked after a successful parent push
  AND no new submodule commits have landed
- **THEN** the script SHALL detect that the gitlink is already current
  and exit 0 without creating an empty commit
