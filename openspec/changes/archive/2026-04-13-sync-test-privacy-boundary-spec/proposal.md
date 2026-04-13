# Proposal: sync-test-privacy-boundary-spec

## Why

Five spec-drift items were identified during `/validate-feature` of the
merged `test-privacy-boundary` change (see
`openspec/changes/archive/2026-04-13-test-privacy-boundary/validation-report.md`).

Each drift item is a case where the **implementation is stricter or
broader than the spec required**, and the supporting tests already exist.
None represent missing functionality — they represent spec text that is
narrower than what shipped. Left unsynced, future refactors could
silently weaken the shipped invariants because the spec doesn't document
them.

This change is pure spec-sync: no code changes, no new tests. It updates
`openspec/specs/test-privacy-boundary/spec.md` to codify five drifts
against the already-shipped implementation at commit `2069784`.

## What Changes

### Drift 1: `ASSISTANT_PERSONAS_DIR` env-var contract (material)

`tests/conftest.py` sets `ASSISTANT_PERSONAS_DIR` via
`os.environ.setdefault`, and `PersonaRegistry`/`RoleRegistry` honor it
with precedence `explicit arg > env var > Path("personas") default`.
Documented in `docs/gotchas.md` G6 and locked by 6 unit tests in
`tests/test_env_var_contract.py`. Not currently a SHALL in the spec.

**Action**: MODIFY the `Public test fixture root` requirement to add
three scenarios covering the env-var mechanism.

### Drift 2: Subprocess `executable=` and `cwd=` kwarg coverage

Layer 2 patches `subprocess.Popen.__init__` to scan not only `args` but
also `executable=` and `cwd=` kwargs (per IMPL_REVIEW finding IR-A4).
Tested via `test_layer2_rejects_subprocess_executable_kwarg` and
`test_layer2_rejects_subprocess_cwd_kwarg`. Spec only mentions `args`.

**Action**: MODIFY the `Two-layer collection-time and runtime boundary
guard` requirement: update the existing subprocess-argv scenario and add
a new scenario for kwarg coverage.

### Drift 3: Layer 1 exclusion list includes hygiene-test files

`tests/_privacy_guard_config.py:SCAN_EXCLUDED_FILES` lists **six** files
(the two guard implementation files + the two hygiene-test files +
`tests/fixtures/` dir + `tests/_helpers/` dir), because the hygiene
tests (`test_ci_workflow_hygiene.py`, `test_workspace_hygiene.py`)
reference forbidden paths as *data* for their scanning logic and use
dynamic-needle construction. Spec currently describes only four
exclusions.

**Action**: MODIFY the `Two-layer collection-time and runtime boundary
guard` requirement: update the scope-exclusion scenario to list the
actual set of excluded paths.

### Drift 4: Submodule conftest `parents[3]` vs spec's `parents[2]`

Spec says "resolved via `parents[2] / roles`" but the shipped
implementation in `personas/personal/tests/conftest.py` uses
`parents[3]`. Both resolve to the same directory (repo root) — `parents[2]`
was the count from a *test file* under
`personas/personal/tests/test_*.py`, while `parents[3]` is the count
from the *conftest file* at `personas/personal/tests/conftest.py`. Wording
drift, not an actual bug.

**Action**: MODIFY the submodule-YAML-shape scenario to describe the
relation abstractly ("two levels above the persona directory") rather
than pinning a specific `parents[N]` count.

### Drift 5: `scripts/push-with-submodule.sh` atomic-push contract

Implementation authors this script as the dual-commit push mechanism
(submodule commit → submodule push → parent gitlink commit → parent
push) with exit code 47 reserved for the dangling-SHA operator-handoff
case. No spec scenario governs its behavior.

**Action**: ADD a new requirement `Atomic dual-commit push wrapper` with
scenarios covering the two modes, the idempotency contract, and the
exit-code-47 semantics.

## Approaches Considered

### Approach 1: Single spec-sync change *(Recommended)*

Bundle all five drift items into one pure spec-modification change. No
code changes. Small, reviewable, merges quickly.

**Pros**:
- One audit unit for "bring the spec in line with what shipped"
- Small PR diff (spec.md only)
- Trivial to review by cross-checking each scenario against the cited test

**Cons**:
- Five unrelated items bundled — slightly harder to revert one individually

**Effort**: S

### Approach 2: One change per drift item

Ship five separate small changes. Each is individually trivial.

**Pros**:
- Each revertible in isolation
- More granular git history

**Cons**:
- Five times the ceremony overhead for the same net diff
- No meaningful parallelism (they all touch the same spec file)

**Effort**: M (ceremony, not content)

### Approach 3: Skip the spec sync; accept the drift

Leave the spec narrower than the implementation. Rely on the tests to
lock the invariants.

**Pros**:
- Zero work

**Cons**:
- Future contributors read the spec, see only what's documented, and may
  refactor away invariants the spec didn't require (e.g. remove the
  `cwd=` subprocess check thinking it's over-implementation)
- Tests would then fail in review, but the confusion + churn is
  avoidable by just keeping the spec honest

**Effort**: 0

## Selected Approach

**Approach 1** — one consolidated spec-sync change.

## Out of scope

- No code changes. Every scenario added here is already satisfied by the
  shipped implementation at commit `2069784`.
- No new tests. Every scenario is already covered by an existing test
  (or by the implementation code under `tests/conftest.py`,
  `tests/_privacy_guard_config.py`, `tests/_privacy_guard_plugin.py`,
  `src/assistant/core/persona.py`, `src/assistant/core/role.py`,
  `scripts/push-with-submodule.sh`).
