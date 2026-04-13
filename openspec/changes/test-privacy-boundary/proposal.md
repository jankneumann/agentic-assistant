# Proposal: test-privacy-boundary

## Why

The public test suite currently reads from, and asserts on, content that lives
inside the private `personas/personal/` git submodule. This creates three
concrete problems:

1. **Private-content leakage into the public repo.** Assertions like
   `tests/test_composition.py:119` (`"Personal Persona Context" in out`) and
   `tests/test_role_registry.py:67` (`"Personal Context Additions" in role.prompt`)
   lift exact strings from the private submodule's prompt files. Anyone reading
   the public test suite learns non-trivial facts about the private persona's
   prompt structure and role overrides.

2. **Silent CI divergence.** Because the public CI cannot clone the private
   submodule, commit `76a313e` added a workaround (`.github/workflows/ci.yml:41-44`)
   that overlays `tests/fixtures/personas/personal/` on top of the empty mount
   point before running pytest. Locally, tests run against the *real* submodule;
   in CI, against the fixture. Developers can add assertions that only work
   locally and have CI pass against stale fixture content — or vice versa.

3. **Submodule cannot be reused harness-agnostic.** The `personas/personal/`
   repo is a *data* artifact. A future MS Agent Framework harness (roadmap P5),
   or a Go/Rust consumer, should be able to check it out and validate its
   shape without importing anything from `src/assistant/*`. Today, the only
   tests that exercise its real content live in the public repo and depend on
   the Python harness's `PersonaRegistry`.

## What Changes

This change enforces a **privacy boundary** between public and private test
scopes:

- **Public tests** (in `tests/`) run exclusively against fixtures in
  `tests/fixtures/personas/`. They never read from `personas/<name>/` at
  runtime and never assert on strings sourced from the real submodule content.
- **Persona-specific integration tests** move into each persona's private
  submodule (e.g. `personas/personal/tests/`), self-contained with their own
  pyproject and a minimal YAML loader — no dependency on `src/assistant/*`.
- **A pytest collection-time guard** in `tests/conftest.py` fails loudly if any
  collected public test file references `personas/(personal|work)/` paths or
  known private-content strings, with an allow-list for
  `tests/fixtures/` and `personas/_template/`.
- **The CI `populate personas/personal from test fixture` step is removed** —
  the conftest redirect makes the workaround unnecessary.
- **Documentation** (`CLAUDE.md` Conventions + `docs/gotchas.md`) records the
  rule so future contributors don't reintroduce the leak.

The boundary guard covers **both `personal` and `work`** from day one (future-
proofing for P6 — `work-persona-config`), even though `personas/work/` is not
yet populated.

## Approaches Considered

### Approach 1: Minimal repoint + conftest guard + submodule-side pytest *(Recommended)*

**Description**: `tests/conftest.py` resolves `personas_dir` to
`REPO_ROOT / "tests" / "fixtures" / "personas"`. Private-content assertions in
public tests are rewritten against fixture values. Persona-specific integration
tests (the ones that genuinely validate the real submodule's YAML shape) move
to `personas/personal/tests/` with their own `pyproject.toml` (pytest + PyYAML)
and no import from `src/assistant/*`. A `pytest_collection_modifyitems` hook in
`tests/conftest.py` inspects each collected test file's source and fails if it
references `personas/(personal|work)/` paths or private-content strings outside
the allow-list.

**Pros**:
- Clean separation: public tests never need the submodule initialized
- Submodule stays harness-agnostic — can be consumed by non-Python harnesses
- Enforcement runs locally *and* in CI (single mechanism, single place)
- Removes the CI populate step and its "keep in sync" maintenance burden
- Matches the team's existing pytest ergonomics on both sides

**Cons**:
- Submodule grows a small `pyproject.toml` dev-dep section (pytest, PyYAML)
- Test writers must remember which conftest to target when touching either side

**Effort**: S

### Approach 2: Dual-mode conftest with `@pytest.mark.integration` marker

**Description**: Public `tests/conftest.py` detects whether
`personas/personal/persona.yaml` exists. If it does, tests marked
`@pytest.mark.integration` are collected; otherwise they are skipped. Private-
coupled tests stay in `tests/` but are moved under `tests/integration/` with
the marker applied. A custom collector refuses imports from
`personas/<name>/` in un-marked tests. The CI populate step stays (so
integration tests run in CI against the fixture).

**Pros**:
- No new repo (submodule stays test-free)
- Single test tree is easier to navigate

**Cons**:
- **Leakage not actually fixed**: integration tests still live in the public
  repo and still assert on private strings. Moving them to a subdirectory is
  cosmetic; `git log` / `git blame` still show private content being asserted.
- CI populate step + fixture sync burden persists
- Submodule is not independently testable by a non-Python harness
- Marker-gated tests are easy to forget about and decay

**Effort**: S

### Approach 3: Externalize private content into env vars / redacted fixtures

**Description**: Treat every string in the fixture as a placeholder. Real
prompts and role overrides are loaded at runtime from env vars or a secrets
directory. Tests assert on structural invariants only (key presence, type,
schema shape) — never on content.

**Pros**:
- Zero private content anywhere in either repo
- Tests are reusable as contract tests for *any* persona

**Cons**:
- Over-engineered for a config-heavy data artifact
- Breaks the current persona model (persona YAML literally embeds prompt
  strings; they're not secrets, they're just *private* in the "not public repo"
  sense, not "do not log" sense)
- Large refactor across `PersonaRegistry`, `RoleRegistry`, and every consumer
- Doesn't address the CI populate-step issue

**Effort**: L

## Selected Approach

**Approach 1** — repoint + guard + submodule-side pytest.

Confirmed during discovery (Gate 1, 2026-04-13):

- **Enforcement mechanism**: pytest conftest collection hook (runs locally
  *and* in CI; single enforcement point).
- **Submodule toolchain**: pytest with a minimal `pyproject.toml` in
  `personas/personal/` declaring pytest + PyYAML as dev deps.
- **Scope**: covers both `personas/personal/` *and* `personas/work/` from day
  one, future-proofing the guard for P6 (`work-persona-config`) even though
  `personas/work/` is not yet populated.
- **CI cleanup**: the `populate personas/personal from test fixture` step
  introduced in `76a313e` is **removed** — the conftest repoint makes it
  redundant.

Approaches 2 and 3 are not selected:

- **Approach 2 (marker-based dual-mode)** — does not actually fix leakage;
  private strings remain in the public repo's `git log`/`git blame` under a
  different directory. Cosmetic, not structural.
- **Approach 3 (env-var placeholders)** — over-engineered. Personas are
  private, not secret; refactoring every consumer of `PersonaRegistry` and
  `RoleRegistry` to load prompts from env vars is disproportionate to the
  problem.
