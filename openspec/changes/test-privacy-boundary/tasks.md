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
  `FORBIDDEN_PATH_NAMES = ("personal", "work")` and
  `ALLOWED_READ_PREFIXES = ("tests/fixtures/", "personas/_template/")`
  plus the four-file exclusion list per D9.
  **Spec scenarios**: test-privacy-boundary/two-layer-collection-time-and-runtime-boundary-guard
  (guard-scope-excludes-its-own-implementation-files)
  **Contracts**: n/a
  **Design decisions**: D2 (single source of truth), D9 (scope)
  **Dependencies**: 2.9

- [ ] 2.11 Write `tests/test_privacy_guard.py` exercising both Layer 1 and
  Layer 2 against synthetic test trees. **Use subprocess-based testing**
  (`subprocess.run([sys.executable, "-m", "pytest", str(tmp_path)],
  capture_output=True)`) rather than the `pytester` fixture — sidesteps
  the `pytest_plugins=["pytester"]` registration requirement (Round 1
  finding I6) and makes the tests independent of pytest plugin discovery.
  Cover at minimum: Layer 1 substring rejection, Layer 1 allow-list, Layer
  1 self-exclusion of `_privacy_guard_config.py`, Layer 2 runtime
  rejection of `Path.read_text` on a forbidden path, Layer 2 allow-list,
  Layer 2 rejection of `Path("personas") / "personal" / "x.yaml"`
  constructed-path read.
  **Spec scenarios**: test-privacy-boundary/two-layer-collection-time-and-runtime-boundary-guard
  (all six scenarios)
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
  `pathlib.Path.open`, `pathlib.Path.read_text`,
  `pathlib.Path.read_bytes`, and `builtins.open` for the duration of
  pytest collection + run. Resolves each requested path, raises
  `_PrivacyBoundaryViolation` (subclass of `pytest.UsageError`) if the
  path resolves under `personas/<name>/` for `<name>` in
  `FORBIDDEN_PATH_NAMES` and is not under any prefix in
  `ALLOWED_READ_PREFIXES`. Wired in via `pytest_plugins =
  ["_privacy_guard_plugin"]` at the top of `tests/conftest.py`.
  **Spec scenarios**: test-privacy-boundary/two-layer-collection-time-and-runtime-boundary-guard
  (Layer 2 scenarios)
  **Contracts**: n/a
  **Design decisions**: D1
  **Dependencies**: 2.11

- [ ] 2.14 Verification: run `uv run pytest tests/` — both guard tests
  pass; full suite stays green. Confirms the guard does not produce false
  positives on legitimate fixture-based tests.
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
  TWO checks (Round 1 finding A1):
  (a) **Static**: grep every `*.py` under `personas/personal/tests/` and
      fail if any contains `import assistant`, `from assistant`,
      `from src.assistant`, `__import__("assistant")`, or
      `importlib.import_module("assistant")` outside this very file.
  (b) **Runtime positive assertion**:
      `with pytest.raises(ImportError): importlib.import_module("assistant")`.
      This proves the venv truly does not have `assistant` installed; the
      static check alone is bypassable via dynamic import idioms.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-tests-assert-assistant-import-fails-at-runtime)
  **Contracts**: n/a
  **Design decisions**: D3, D4
  **Dependencies**: 3.3

- [ ] 3.6 Verification — fresh-venv standalone proof. Replaces the
  `PYTHONPATH=/dev/null` approach (Round 1 finding A1, also acknowledged
  by F1 with regard to root-pytest testpaths). Create a script
  `scripts/verify-submodule-standalone.sh` that:
  (1) creates a fresh venv: `python -m venv /tmp/spb-venv`,
  (2) installs only pytest + pyyaml: `/tmp/spb-venv/bin/pip install pytest pyyaml`,
  (3) runs `/tmp/spb-venv/bin/pytest personas/personal/tests/`,
  (4) asserts exit status 0,
  (5) cleans up via `trap`.
  Also independently verify `cd personas/personal && uv run pytest tests/`
  succeeds when the submodule is consumed in-place from a parent checkout.
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
  `.github/workflows/*.yml` for references to `personas/personal/` or
  `personas/work/`. Fails if any reference is not paired with an explicit
  copy-from-`tests/fixtures/` step (or if any `.yml` mentions the
  forbidden path at all, since after D6 there should be zero such
  references). Catches the regression class flagged by Round 1 finding A7.
  **Spec scenarios**: test-privacy-boundary/ci-simplification-and-forward-compatible-hygiene-check
  (workflow-hygiene-test-rejects-future-leakage-paths)
  **Contracts**: n/a
  **Design decisions**: R4
  **Dependencies**: 2.10 (uses the same FORBIDDEN_PATH_NAMES constants),
  4.1

## Phase 5 — Integration

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

- [ ] 5.3-alt Fallback for missing private-repo write access (Round 1
  finding I9): if 5.3a's push fails due to credential absence, the
  dispatcher SHALL quarantine `wp-submodule-tests` with a clearly-flagged
  status (`requires-private-repo-write`) and emit a handoff message
  containing the exact `git -C personas/personal push <branch>` command
  and the parent SHA-bump commit needed to follow up. The change is not
  marked failed; it waits for an operator with credentials.
  **Spec scenarios**: n/a (ops)
  **Contracts**: n/a
  **Design decisions**: R3
  **Dependencies**: 5.3a (only fires on its failure)

- [ ] 5.4 Push parent branch `openspec/test-privacy-boundary` to origin
  and open PR. (Subsumed by 5.3b's `--parent-only` path; this task only
  applies if 5.3b is split or skipped.)
  **Spec scenarios**: n/a (ops)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 5.3b
