# Tasks: test-privacy-boundary

Task ordering follows TDD: test tasks precede the implementation tasks they
verify. Each implementation task declares its test-task dependency.

## Phase 1 — Contracts scaffold

- [ ] 1.1 Create `contracts/README.md` documenting that no API, DB, or event
  contract sub-types apply to this change (the change only touches test
  infrastructure and CI, no external interfaces).
  **Spec scenarios**: none (documentation-only)
  **Contracts**: n/a
  **Design decisions**: n/a
  **Dependencies**: none

## Phase 2 — Public test boundary (TDD)

- [ ] 2.1 Write `tests/test_privacy_guard.py` — exercises the collection-time
  guard against three synthetic in-memory "bad" test files (path reference,
  private-content string, `_template` path that should be allowed). Uses
  `pytest`'s `pytester` fixture.
  **Spec scenarios**: test-privacy-boundary/collection-time-boundary-guard
  (guard-rejects-forbidden-path-reference, guard-rejects-private-content-string,
  guard-allows-template-and-fixture-references, guard-covers-both-personal-and-work)
  **Contracts**: n/a
  **Design decisions**: D1 (collection-time, not runtime), D2 (deny-list as
  module constants)
  **Dependencies**: 1.1

- [ ] 2.2 Implement `pytest_collection_modifyitems` hook in
  `tests/conftest.py`. Define `FORBIDDEN_PATH_SUBSTRINGS`,
  `FORBIDDEN_CONTENT_STRINGS`, `ALLOWED_PATH_SUBSTRINGS` module constants per
  D2. Read each collected `item.fspath`'s source text once per file
  (memoize), fail with `pytest.UsageError` on first violation.
  **Spec scenarios**: test-privacy-boundary/collection-time-boundary-guard
  (all four scenarios)
  **Contracts**: n/a
  **Design decisions**: D1, D2
  **Dependencies**: 2.1

- [ ] 2.3 Write test asserting that `personas_dir` fixture resolves to
  `tests/fixtures/personas/`, not `REPO_ROOT/personas/`.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-personas_dir-fixture-resolves-to-fixtures-root)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 1.1

- [ ] 2.4 Repoint `personas_dir` fixture in `tests/conftest.py` from
  `REPO_ROOT / "personas"` to `REPO_ROOT / "tests" / "fixtures" / "personas"`.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-personas_dir-fixture-resolves-to-fixtures-root,
  public-test-suite-passes-without-submodule-content)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.3

- [ ] 2.5 Scrub private-content assertions from `tests/test_composition.py`
  (specifically `test_composition_against_real_configs` at lines 112-122).
  Rewrite to assert only against fixture-derived content; move any assertion
  that depends on real-persona prompt strings to Phase 3 (submodule suite) or
  delete if redundant with the fixture-based variant.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-test-suite-passes-without-submodule-content)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.2, 2.4

- [ ] 2.6 Scrub private-content assertions from `tests/test_role_registry.py`
  — in particular line 67 (`"Personal Context Additions"`). Rewrite against
  fixture values from `tests/fixtures/personas/personal/roles/researcher.yaml`;
  move any real-content check to the submodule suite.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-test-suite-passes-without-submodule-content);
  test-privacy-boundary/collection-time-boundary-guard
  (guard-rejects-private-content-string)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.2, 2.4

- [ ] 2.7 Audit `tests/test_persona_registry.py` line 83
  (`"Personal Persona Context" in cfg.prompt_augmentation`) and rewrite
  against fixture content.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.2, 2.4

- [ ] 2.8 Audit `tests/test_delegation.py` and `tests/test_cli.py` for any
  residual assertions on private-content strings; rewrite against fixture
  values. These files primarily reference the word `"personal"` as a persona
  name (which is not private), so most uses are fine.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.2, 2.4

- [ ] 2.9 Verification: run `uv run pytest tests/` with the real
  `personas/personal/` submodule temporarily moved aside
  (`mv personas/personal /tmp/pers-backup && git status`). Must exit 0.
  Restore after.
  **Spec scenarios**: test-privacy-boundary/public-test-fixture-root
  (public-test-suite-passes-without-submodule-content)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.5, 2.6, 2.7, 2.8

## Phase 3 — Submodule self-contained test suite

- [ ] 3.1 Write `personas/personal/tests/test_persona_yaml.py` — asserts
  `persona.yaml` contains required top-level keys (`name`, `display_name`,
  `database`, `auth`, `harnesses`, `default_role`) and that all `*_env` values
  follow the `PERSONAL_*` prefix convention. Uses `yaml.safe_load` only; no
  imports from `assistant.*`.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-tests-run-standalone, submodule-suite-validates-yaml-shape)
  **Contracts**: n/a
  **Design decisions**: D3 (direct YAML parse, no PersonaConfig),
  D4 (pyproject deps = pytest + pyyaml)
  **Dependencies**: 1.1

- [ ] 3.2 Write `personas/personal/tests/test_role_overrides.py` — for each
  `*.yaml` under `personas/personal/roles/`, assert a matching base role exists
  at `<parent>/roles/<name>/role.yaml`. If the parent repo's `roles/` directory
  is not resolvable (standalone mode), `pytest.skip` with a descriptive
  message per D5.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-suite-validates-yaml-shape)
  **Contracts**: n/a
  **Design decisions**: D3, D5 (parent roles resolved via `../../roles`)
  **Dependencies**: 1.1

- [ ] 3.3 Write `personas/personal/tests/conftest.py` — minimal fixtures that
  expose `persona_root = Path(__file__).resolve().parents[1]` and optionally
  `parent_roles_dir` (None if not present). Zero imports from `assistant.*`.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-tests-run-standalone)
  **Contracts**: n/a
  **Design decisions**: D3, D5
  **Dependencies**: 3.1, 3.2

- [ ] 3.4 Write `personas/personal/pyproject.toml` — declare `pytest>=8` and
  `pyyaml>=6` as dev dependencies. No `build-backend`; this is not an
  installable package per D4.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-tests-run-standalone)
  **Contracts**: n/a
  **Design decisions**: D4
  **Dependencies**: none

- [ ] 3.5 Write assertion (as a meta-test at
  `personas/personal/tests/test_no_assistant_import.py`) that greps every
  `*.py` under `personas/personal/tests/` and fails if any contains
  `import assistant`, `from assistant`, or `from src.assistant`.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-tests-run-standalone)
  **Contracts**: n/a
  **Design decisions**: D3
  **Dependencies**: 3.3

- [ ] 3.6 Verification: `cd personas/personal && uv run pytest tests/` exits
  0. Also verify `PYTHONPATH=/dev/null uv run pytest personas/personal/tests/`
  (proof of standalone) exits 0.
  **Spec scenarios**: test-privacy-boundary/self-contained-persona-submodule-test-suite
  (submodule-tests-run-standalone)
  **Contracts**: n/a
  **Design decisions**: D3
  **Dependencies**: 3.1, 3.2, 3.3, 3.4, 3.5

## Phase 4 — CI and documentation

- [ ] 4.1 Remove the `populate personas/personal from test fixture` step from
  `.github/workflows/ci.yml` (lines 41-44 per the CI investigation).
  **Spec scenarios**: test-privacy-boundary/ci-simplification
  (ci-omits-the-populate-personas-step)
  **Contracts**: n/a
  **Design decisions**: D6 (remove, not keep as safety net)
  **Dependencies**: 2.4

- [ ] 4.2 Add a new gotcha entry `G6: Private-persona content leakage via
  public test assertions` to `docs/gotchas.md` following the existing
  symptom/root-cause/fix/prevention format.
  **Spec scenarios**: test-privacy-boundary/documentation-of-the-privacy-boundary-rule
  (docs-gotchas-md-records-the-failure-mode)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.2

- [ ] 4.3 Update `CLAUDE.md` "Conventions" section with the bullet: "Public
  tests use fixtures only (`tests/fixtures/personas/`); persona-specific
  tests live in each persona's private submodule and must be self-contained
  (no imports from `src/assistant/*`)."
  **Spec scenarios**: test-privacy-boundary/documentation-of-the-privacy-boundary-rule
  (claude-md-records-the-convention)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: none

## Phase 5 — Integration

- [ ] 5.1 Run `openspec validate test-privacy-boundary --strict` and fix any
  validation errors.
  **Spec scenarios**: n/a
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: all of Phase 2, 3, 4

- [ ] 5.2 Run full `uv run pytest` at the repo root — all tests green.
  **Spec scenarios**: all
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 2.9, 3.6, 4.1, 4.2, 4.3

- [ ] 5.3 Commit submodule content inside `personas/personal/`, push to its
  private remote (e.g. `github.com/jankneumann/agentic-assistant-config-personal`),
  then `git add personas/personal` in the parent to update the submodule SHA
  pointer. Commit parent changes.
  **Spec scenarios**: n/a (ops)
  **Contracts**: n/a
  **Design decisions**: D7 (submodule + parent as two commits)
  **Dependencies**: 3.6, 5.2

- [ ] 5.4 Push parent branch `openspec/test-privacy-boundary` to origin and
  open PR.
  **Spec scenarios**: n/a (ops)
  **Contracts**: n/a
  **Design decisions**: none
  **Dependencies**: 5.3
