# Tasks: test-privacy-boundary

Task ordering follows TDD: test tasks precede the implementation tasks they
verify. Each implementation task declares its test-task dependency.

**Phase 2 ordering note (Round 1 fix for I1)**: The two-layer guard
implementation (`2.10`, `2.11`) is intentionally sequenced **after** the
public-test scrub tasks (`2.4`–`2.8`). If the guard were enabled while the
existing tests still contained literal forbidden substrings, every guard
self-test invocation would fail collection on the unscrubbed tests. The
scrub establishes a clean baseline; the guard then locks it in.

## Phase 1 — Contracts scaffold

- [ ] 1.1 Create `contracts/README.md` documenting that no API, DB, or
  event contract sub-types apply to this change (the change only touches
  test infrastructure and CI, no external interfaces).
  **Spec scenarios**: none (documentation-only)
  **Contracts**: n/a
  **Design decisions**: n/a
  **Dependencies**: none

## Phase 2 — Public test boundary (TDD; scrub-then-guard ordering)

- [ ] 2.1 Add a `FIXTURE_PERSONA_SENTINEL` marker string to
  `tests/fixtures/personas/personal/prompt.md` (and the corresponding role
  yamls if they participate in composition) so the fixture-based
  composition test (task 2.3) has a unique-to-fixture string to assert on.
  Choose a string that is unmistakably fixture-only (e.g.
  `"FIXTURE_PERSONA_SENTINEL_v1"`) and document it inline.
  **Spec scenarios**: test-privacy-boundary/replacement-integration-coverage-for-compose_system_prompt
  (fixture-based-composition-test-asserts-on-a-fixture-sentinel)
  **Contracts**: n/a
  **Design decisions**: D2 (we no longer track private-content strings; we
  track fixture sentinels instead)
  **Dependencies**: 1.1

- [ ] 2.2 Repoint `personas_dir` fixture in `tests/conftest.py` from
  `REPO_ROOT / "personas"` to `REPO_ROOT / "tests" / "fixtures" / "personas"`.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-personas_dir-fixture-resolves-to-fixtures-root)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 1.1

- [ ] 2.3 Write a fixture-based composition integration test in
  `tests/test_composition.py` that loads the fixture `personal` persona +
  `researcher` role, calls `compose_system_prompt`, and asserts that the
  output contains `FIXTURE_PERSONA_SENTINEL_v1`. This replaces the lost
  end-to-end coverage of `compose_system_prompt` against real persona data
  (Round 1 finding F4).
  **Spec scenarios**: test-privacy-boundary/replacement-integration-coverage-for-compose_system_prompt
  (fixture-based-composition-test-asserts-on-a-fixture-sentinel)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.1, 2.2

- [ ] 2.4 Scrub `test_composition_against_real_configs` (existing test in
  `tests/test_composition.py:112-122`) — delete it; replaced by 2.3.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-test-suite-passes-without-submodule-content)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.3

- [ ] 2.5 Scrub private-content assertions from `tests/test_role_registry.py`
  — in particular line 67 (`"Personal Context Additions"`). Rewrite all
  assertions against fixture values from
  `tests/fixtures/personas/personal/roles/researcher.yaml`. Where the real
  persona's role override carried unique content not present in the
  fixture, either (a) add the equivalent fixture-only sentinel and assert
  on it, or (b) move the assertion to the submodule suite (Phase 3).
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-test-suite-passes-without-submodule-content)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.2

- [ ] 2.6 Audit `tests/test_persona_registry.py` line 83
  (`"Personal Persona Context" in cfg.prompt_augmentation`) and rewrite
  against the `FIXTURE_PERSONA_SENTINEL_v1` (or another fixture-defined
  marker added in 2.1).
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.1, 2.2

- [ ] 2.7 Audit `tests/test_delegation.py` for any residual assertions on
  private-content strings; rewrite against fixture values.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.2

- [ ] 2.8 Audit `tests/test_cli.py` for any residual private-string
  assertions; rewrite against fixture values. Most uses of the word
  `"personal"` here are persona names (not private), so most uses are
  fine — verify and document each.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.2

- [ ] 2.9 Verification: invoke `bash scripts/verify-public-tests-standalone.sh`
  (created in this task). The script wraps `git submodule deinit -f
  personas/personal`, runs `uv run pytest tests/`, then restores via
  `git submodule update --init personas/personal`. The wrapper uses
  `trap` to guarantee restoration even on pytest failure or interrupt.
  Replaces the unsafe `mv` approach (Round 1 finding I5).
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-test-suite-passes-without-submodule-content)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.4, 2.5, 2.6, 2.7, 2.8

- [ ] 2.10 Create `tests/_privacy_guard_config.py` defining
  `FORBIDDEN_PATH_NAMES = ("personal", "work")`,
  `ALLOWED_READ_PREFIXES = ("tests/fixtures/", "personas/_template/")`,
  and the **six-file** exclusion list per D9 (updated from four after
  Round 2 B-N4): `_privacy_guard_config.py`, `_privacy_guard_plugin.py`,
  `test_ci_workflow_hygiene.py`, `test_workspace_hygiene.py`, plus the
  `tests/fixtures/` directory and `tests/_helpers/` directory (added per
  D8's note that Python helpers relocate there).
  **Spec scenarios**: test-privacy-boundary/two-layer-collection-time-and-runtime-boundary-guard
  (guard-scope-excludes-its-own-implementation-files)
  **Contracts**: n/a
  **Design decisions**: D2 (single source of truth), D9 (scope including
  hygiene-test exclusions)
  **Dependencies**: 2.9

- [ ] 2.11 Write `tests/test_privacy_guard.py` exercising both Layer 1 and
  Layer 2 against synthetic test trees. **Use subprocess-based testing**
  (`subprocess.run([sys.executable, "-m", "pytest", str(tmp_path)],
  capture_output=True)`) rather than the `pytester` fixture — sidesteps
  the `pytest_plugins=["pytester"]` registration requirement (Round 1
  finding I6) and makes the tests independent of pytest plugin discovery.
  Cover at minimum (expanded per Round 2 B-N1/B-N2/B-N8):
  - Layer 1 substring rejection.
  - Layer 1 allow-list.
  - Layer 1 self-exclusion of `_privacy_guard_config.py` and
    `_privacy_guard_plugin.py`, `test_ci_workflow_hygiene.py`,
    `test_workspace_hygiene.py`.
  - Layer 2 runtime rejection of `Path.read_text` on a forbidden path.
  - Layer 2 runtime rejection of `os.open` on a forbidden path.
  - Layer 2 runtime rejection of `io.FileIO` (transitively, via os.open).
  - Layer 2 runtime rejection of `subprocess.run(['cat', forbidden_path])`
    — both literal and split-argv cases.
  - Layer 2 allow-list (reads under `tests/fixtures/` proceed).
  - Layer 2 rejection of `Path("personas") / "personal" / "x.yaml"`
    constructed-path read.
  - Layer 2 self-probe fires when plugin fails to install (simulate by
    monkey-patching the plugin's install function to no-op, assert
    session fails).
  **Spec scenarios**: test-privacy-boundary/two-layer-collection-time-and-runtime-boundary-guard
  (all scenarios including layer-2-rejects-a-forbidden-subprocess-argv
  and layer-2-self-probes-after-installation)
  **Contracts**: n/a
  **Design decisions**: D1, D9
  **Dependencies**: 2.10

- [ ] 2.12 Implement Layer 1 (`pytest_collection_modifyitems` hook) in
  `tests/conftest.py`. Read each scanned file's source text once
  (memoize), match against `FORBIDDEN_PATH_NAMES` substrings, fail with
  `pytest.UsageError` on first violation. Failure message names the file
  and matched deny-list entry but **does not** echo file content (per
  spec scenario "Guard failure messages do not echo private payloads").
  **Spec scenarios**: test-privacy-boundary/two-layer-collection-time-and-runtime-boundary-guard
  (Layer 1 scenarios + failure-messages-do-not-echo-private-payloads)
  **Contracts**: n/a
  **Design decisions**: D1, D9
  **Dependencies**: 2.11

- [ ] 2.13 Implement Layer 2 in `tests/_privacy_guard_plugin.py`. Patches
  **six** I/O entry points for the duration of pytest collection + run
  (expanded per Round 2 B-N1/B-N2):
  - `pathlib.Path.open`
  - `pathlib.Path.read_text`
  - `pathlib.Path.read_bytes`
  - `builtins.open`
  - `os.open` (canonical syscall choke point covering `io.FileIO`,
    `codecs.open`, `io.open`)
  - `subprocess.Popen.__init__` (scans argv elements for forbidden path
    substrings, closing the `subprocess.run(['cat', 'personas/...'])`
    bypass class)
  Resolves each requested path, raises `_PrivacyBoundaryViolation`
  (subclass of `pytest.UsageError`) if the path resolves under
  `personas/<name>/` for `<name>` in `FORBIDDEN_PATH_NAMES` and is not
  under any prefix in `ALLOWED_READ_PREFIXES`. For `subprocess.Popen`,
  raises if any argv element contains `personas/<name>/` substring.
  Wired in via `pytest_plugins = ["_privacy_guard_plugin"]` at the top
  of `tests/conftest.py`.
  **Plugin self-probe (B-N8)**: at `pytest_configure` time, after
  installing patches, the plugin SHALL open a canary forbidden path
  (under `personas/personal/`, non-allow-listed) and assert
  `_PrivacyBoundaryViolation` is raised. If the probe does NOT raise,
  the plugin fails the session via
  `pytest.UsageError("Layer 2 privacy guard failed to install")`.
  Prevents silent disable when future CPython changes break method-level
  monkey-patching.
  **Spec scenarios**: test-privacy-boundary/two-layer-collection-time-and-runtime-boundary-guard
  (Layer 2 scenarios including layer-2-rejects-a-forbidden-subprocess-argv
  and layer-2-self-probes-after-installation)
  **Contracts**: n/a
  **Design decisions**: D1
  **Dependencies**: 2.11

- [ ] 2.14 Verification: run `uv run pytest tests/` — both guard tests
  pass; full suite stays green. Confirms the guard does not produce
  false positives on legitimate fixture-based tests. Note that the two
  hygiene tests (4.4, 4.5) are authored in `wp-ci-cleanup` (after the
  populate-step removal in 4.1) rather than here, so this verification
  does not attempt to run them — they are exercised in 5.2a after
  wp-ci-cleanup lands.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-test-suite-passes-without-submodule-content)
  **Contracts**: n/a
  **Design decisions**: D1, D9
  **Dependencies**: 2.12, 2.13

## Phase 3 — Submodule self-contained test suite

- [ ] 3.1 Write `personas/personal/tests/test_persona_yaml.py` — asserts
  `persona.yaml` contains required top-level keys (`name`, `display_name`,
  `database`, `auth`, `harnesses`, `default_role`). Explicitly enumerates
  the three env-reference checks (Round 1 finding I7):
  (a) `database.url_env` starts with `PERSONAL_`,
  (b) `graphiti.url_env` starts with `PERSONAL_` if the `graphiti` block
  exists (else assert intentional absence),
  (c) every value of `auth.config.*_env` starts with `PERSONAL_`.
  Uses `yaml.safe_load` only; no imports from `assistant.*`.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-suite-validates-yaml-shape)
  **Contracts**: n/a
  **Design decisions**: D3 (direct YAML parse, no PersonaConfig),
  D4 (pyproject deps = pytest + pyyaml)
  **Dependencies**: 1.1

- [ ] 3.2 Write `personas/personal/tests/test_role_overrides.py` — for
  each `*.yaml` under `personas/personal/roles/`, assert a matching base
  role exists at `<parent>/roles/<name>/role.yaml`. If the parent repo's
  `roles/` directory is not resolvable, the test SHALL `pytest.fail`
  unless `ALLOW_STANDALONE_SUBMODULE_SKIP=1` is set, in which case it
  SHALL `pytest.skip` with a loud message naming the env var (Round 1
  finding A6).
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-suite-validates-yaml-shape, standalone-mode-requires-explicit-opt-in)
  **Contracts**: n/a
  **Design decisions**: D3, D5
  **Dependencies**: 1.1

- [ ] 3.3 Write `personas/personal/tests/conftest.py` — minimal fixtures
  that expose `persona_root = Path(__file__).resolve().parents[1]` and
  optionally `parent_roles_dir` (None if not present). Zero imports from
  `assistant.*`.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-pyproject-declares-an-isolated-workspace)
  **Contracts**: n/a
  **Design decisions**: D3, D5
  **Dependencies**: 3.1, 3.2

- [ ] 3.4 Write `personas/personal/pyproject.toml` — declare `pytest>=8`
  and `pyyaml>=6` as dev dependencies, plus a `[tool.uv]` block declaring
  the directory as a non-package and explicitly empty
  `workspace.members = []`. This prevents `uv` from walking up to discover
  the parent project (Round 1 finding A1).
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-pyproject-declares-an-isolated-workspace)
  **Contracts**: n/a
  **Design decisions**: D4
  **Dependencies**: none

- [ ] 3.5 Write `personas/personal/tests/test_no_assistant_import.py` with
  TWO checks (Round 1 finding A1, refined per Round 2 B-N5):
  (a) **Static**: grep every `*.py` under `personas/personal/tests/` and
      fail if any contains `import assistant`, `from assistant`,
      `from src.assistant`, `__import__("assistant")`, or
      `importlib.import_module("assistant")` outside this very file.
  (b) **Runtime positive assertion**:
      `with pytest.raises(ImportError): importlib.import_module("assistant.core.persona")`.
      The **qualified path** (`.core.persona`) is distinctive to this
      project and will NOT collide with the unrelated PyPI package also
      named `assistant` (Round 2 B-N5). A bare
      `importlib.import_module("assistant")` would spuriously succeed in
      a venv where the PyPI squatter is installed and produce a misleading
      failure unrelated to the privacy contract.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-tests-assert-assistant-import-fails-at-runtime)
  **Contracts**: n/a
  **Design decisions**: D3, D4
  **Dependencies**: 3.3

- [ ] 3.6 Verification — fresh-venv standalone proof. Replaces the
  `PYTHONPATH=/dev/null` approach (Round 1 finding A1, refined per
  Round 2 B-N7). Create a script `scripts/verify-submodule-standalone.sh`
  that:
  (1) creates a fresh venv: `python -m venv /tmp/spb-venv`,
  (2) installs only pytest + pyyaml with pinned minimums:
      `/tmp/spb-venv/bin/pip install 'pytest>=8' 'pyyaml>=6'`,
  (3) `cd personas/personal` **before** invoking pytest (Round 2 B-N7 —
      this makes pytest's rootdir the submodule's pyproject, not the
      parent's, so the parent's `pytest_plugins` do NOT load against
      submodule tests),
  (4) runs `/tmp/spb-venv/bin/pytest tests/ --rootdir=. --override-ini='addopts='`,
  (5) asserts exit status 0,
  (6) cleans up via `trap` on both EXIT and any interrupt signal.
  Also independently verify `cd personas/personal && uv run pytest tests/`
  succeeds when the submodule is consumed in-place from a parent checkout
  (this exercises the `[tool.uv].package = false` boundary from D4 +
  the workspace-forward-compat guard from task 4.5).
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (standalone-proof-verification-uses-a-fresh-venv,
  submodule-pyproject-declares-an-isolated-workspace)
  **Contracts**: n/a
  **Design decisions**: D4
  **Dependencies**: 3.1, 3.2, 3.3, 3.4, 3.5

## Phase 4 — CI and documentation

- [ ] 4.1 Remove the `populate personas/personal from test fixture` step
  from `.github/workflows/ci.yml` (lines 41-44 per the CI investigation).
  **Spec scenarios**: test-privacy-boundary/ci-simplification-and-forward-compatible-hygiene-check
  (ci-omits-the-populate-personas-step)
  **Contracts**: n/a
  **Design decisions**: D6
  **Dependencies**: 2.2 (fixture repoint must land first so CI remains
  green after this step is removed)

- [ ] 4.2 Add a new gotcha entry `G6: Private-persona content leakage via
  public test assertions` to `docs/gotchas.md` following the existing
  symptom/root-cause/fix/prevention format. Cover both the literal-path
  leak (Layer 1 catches) and the path-construction leak (Layer 2 catches).
  Also document `ALLOW_STANDALONE_SUBMODULE_SKIP=1` and the workflow-
  hygiene test as related entries (G7).
  **Spec scenarios**: test-privacy-boundary/documentation-of-the-privacy-boundary-rule
  (docs-gotchas-md-records-the-failure-mode)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.12, 2.13

- [ ] 4.3 Update `CLAUDE.md` "Conventions" section with the bullet:
  "Public tests use fixtures only (`tests/fixtures/personas/`);
  persona-specific tests live in each persona's private submodule and
  must be self-contained (no imports from `src/assistant/*`); the
  two-layer privacy guard in `tests/conftest.py` enforces this at
  collection time and at runtime."
  **Spec scenarios**: test-privacy-boundary/documentation-of-the-privacy-boundary-rule
  (claude-md-records-the-convention)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: none

- [ ] 4.4 Write `tests/test_ci_workflow_hygiene.py` — scans every
  `.github/workflows/*.yml` (and `*.yaml`, and `.github/actions/**/action.yml`)
  for references to forbidden persona paths. **Constructs its forbidden
  needle dynamically** from
  `tests._privacy_guard_config.FORBIDDEN_PATH_NAMES`
  (per Round 2 B-N4):
  ```python
  from tests._privacy_guard_config import FORBIDDEN_PATH_NAMES
  needles = tuple(f"personas/{name}/" for name in FORBIDDEN_PATH_NAMES)
  ```
  so the file's own source never contains the literal forbidden
  substring and Layer 1 doesn't self-trip. (Belt-and-suspenders: this
  file is ALSO in the Layer 1 exclusion list per 2.10.) Fails if any
  matched reference is not paired with an explicit
  copy-from-`tests/fixtures/` step — or, since D6 removes the populate
  step entirely, if any `.yml`/`.yaml`/`action.yml` mentions the
  forbidden path at all.
  **Spec scenarios**: test-privacy-boundary/ci-simplification-and-forward-compatible-hygiene-check
  (workflow-hygiene-test-rejects-future-leakage-paths)
  **Contracts**: n/a
  **Design decisions**: R4, D9 (dynamic needle + exclusion)
  **Dependencies**: 2.10 (uses the FORBIDDEN_PATH_NAMES constants + is
  in the exclusion list), 4.1

- [ ] 4.5 Write `tests/test_workspace_hygiene.py` — parses the parent
  `pyproject.toml` (via `tomllib`) and asserts that either (a) no
  `[tool.uv.workspace]` section exists, or (b) if it does, `members` does
  NOT contain any glob matching `personas/personal/` or `personas/work/`
  (e.g. `personas/*`, `personas/**`). Guards against a future
  dev-ergonomics change drawing the submodule into the parent venv and
  silently defeating self-containment (Round 2 B-N6). Like 4.4, this
  file is in the Layer 1 exclusion list (per 2.10) and uses dynamic
  needle construction.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (parent-pyproject-does-not-include-submodule-in-a-uv-workspace)
  **Contracts**: n/a
  **Design decisions**: D4 (forward-compat guard)
  **Dependencies**: 2.10

## Phase 5 — Integration

- [ ] 5.0 Create `scripts/push-with-submodule.sh` (authoring task added per
  Round 2 finding B-N3 — previously referenced by 5.3a/5.3b but not
  authored by any task). The script SHALL support two invocation modes:
  - `--submodule-only`: `cd personas/personal`, verify we're at
    `origin/main` or a documented branch, `git push` to the private
    remote, print the pushed SHA to stdout as the last line.
  - `--parent-only`: verify the parent branch is rebased onto
    `origin/main`, `git add personas/personal` (gitlink update), commit
    with a message including the submodule SHA, push parent branch.
    If push fails after submodule push had succeeded, log the
    dangling-SHA diagnostic (submodule SHA + parent HEAD at failure +
    suggested recovery command: `git -C personas/personal push -d
    origin <branch-with-dangling-sha>` or open an operator ticket) and
    exit with a distinctive non-zero code (e.g. 47) that the 5.3-alt
    dispatcher recognizes.
  The script SHALL be idempotent within a mode (re-invoking
  `--parent-only` after a successful push is a no-op) and SHALL NOT
  require `--submodule-only` and `--parent-only` to be invoked by the
  same process. Exit-code contract documented inline.
  **Spec scenarios**: n/a (ops tooling)
  **Contracts**: n/a
  **Design decisions**: D7 (atomic push wrapper)
  **Dependencies**: none

- [ ] 5.1 Run `openspec validate test-privacy-boundary --strict` and fix
  any validation errors.
  **Spec scenarios**: n/a
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: all of Phase 2, 3, 4

- [ ] 5.2a Run `uv run pytest tests/` from repo root (covers Phase 2 +
  Phase 4 work, exercises both guard layers and the workflow-hygiene
  test). Must exit 0.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root,
  test-privacy-boundary/two-layer-collection-time-and-runtime-boundary-guard,
  test-privacy-boundary/ci-simplification-and-forward-compatible-hygiene-check
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.14, 4.4

- [ ] 5.2b Run `bash scripts/verify-submodule-standalone.sh` (created in
  3.6) — covers Phase 3. Pyproject's `testpaths = ["tests"]` scopes the
  root-level pytest to `tests/`, so submodule tests **must** be run via
  the dedicated script (Round 1 finding F1).
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (all)
  **Contracts**: n/a
  **Design decisions**: D4
  **Dependencies**: 3.6

- [ ] 5.3a Inside the submodule, commit submodule content and push to its
  private remote via `bash scripts/push-with-submodule.sh --submodule-only`
  (or equivalent). This step lives in `wp-submodule-tests` (Round 1
  finding F5/I3).
  **Spec scenarios**: n/a (ops)
  **Contracts**: n/a
  **Design decisions**: D7
  **Dependencies**: 5.2b

- [ ] 5.3b In the parent repo, `git add personas/personal` to update the
  submodule SHA pointer, commit, and push the parent branch via
  `bash scripts/push-with-submodule.sh --parent-only`. Lives in
  `wp-integration`. The atomic wrapper handles the failure mode where
  parent push fails after submodule push succeeded (logs dangling SHA,
  emits operator-recovery command — Round 1 finding A8).
  **Spec scenarios**: n/a (ops)
  **Contracts**: n/a
  **Design decisions**: D7
  **Dependencies**: 5.3a

- [ ] 5.3-alt Fallback for missing private-repo write access
  (Round 1 finding I9, trigger semantics clarified per Round 2 A-N2).
  This task is **dispatch-time-driven**, not runtime-driven: the
  dispatcher inspects `wp-submodule-tests.constraints.requires_private_repo_write`
  and, if credentials are not available in the execution environment,
  the dispatcher SHALL quarantine `wp-submodule-tests` with a
  clearly-flagged status (`requires-private-repo-write`) and emit a
  handoff message containing (a) the exact
  `git -C personas/personal push <branch>` command, (b) the parent
  SHA-bump commit message template, and (c) the exit code 47 diagnostic
  from `scripts/push-with-submodule.sh` if 5.3a had been attempted.
  Additionally, if 5.3a is actually attempted (credentials looked
  available but push failed at runtime due to auth error or drift), the
  same quarantine path fires on receiving exit code 47. The change is
  NOT marked failed in either case; it waits for an operator with
  credentials. This dual trigger (dispatch-time + runtime exit-code 47)
  is the explicit contract.
  **Spec scenarios**: n/a (ops)
  **Contracts**: n/a
  **Design decisions**: R3 (private-repo write access)
  **Dependencies**: none at dispatch time; 5.3a at runtime

- [ ] 5.4 Open the pull request for the parent branch
  `openspec/test-privacy-boundary` via `gh pr create`. Title:
  `plan(test-privacy-boundary): privacy-boundary between public tests
  and persona submodules`. Body: proposal summary + convergence trail
  (rounds, findings resolved, remaining known gaps per design R2) +
  the two-commit topology notice (parent PR references a specific
  submodule SHA; reviewers must check out the submodule at that SHA to
  review the submodule-side content, or be pointed at the private-repo
  PR). This task is **not subsumed by 5.3b** (clarified per Round 2
  A-N1); 5.3b pushes the parent branch, 5.4 opens the PR. They are
  distinct steps.
  **Spec scenarios**: n/a (ops)
  **Contracts**: n/a
  **Design decisions**: D7 (two-commit topology visibility)
  **Dependencies**: 5.3b
