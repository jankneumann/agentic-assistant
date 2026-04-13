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

### Approach 1: Repoint + two-layer guard + self-contained submodule pytest *(Recommended)*

**Description**: `tests/conftest.py` resolves `personas_dir` to
`REPO_ROOT / "tests" / "fixtures" / "personas"`. Public tests are scrubbed of
any reference to real-submodule content and rewritten against fixture-defined
values (including a `FIXTURE_PERSONA_SENTINEL` marker for end-to-end
composition coverage). Persona-specific integration tests move to
`personas/personal/tests/` with their own `pyproject.toml` (pytest + PyYAML,
plus a `[tool.uv]` workspace boundary so `uv` does not reuse the parent
venv) and no import from `src/assistant/*`. Self-containment is proven by a
fresh-venv test run, not by `PYTHONPATH` tricks. A **two-layer** privacy
guard is wired into `tests/conftest.py`:
(1) a collection-time substring scan that rejects literal
`personas/personal/` or `personas/work/` references in test files and
conftests, and (2) a runtime filesystem guard (a pytest plugin patching
`pathlib.Path.open`, `read_text`, `read_bytes`, and `builtins.open`) that
rejects path-constructed reads into the same namespaces — closing the
`Path("personas") / name / "x.yaml"` bypass that defeats substring-only
matching.

**Pros**:
- Clean separation: public tests never need the submodule initialized
- Submodule stays harness-agnostic — can be consumed by non-Python harnesses
- Two-layer guard catches both literal and constructed-path leaks
- Enforcement runs locally *and* in CI (single mechanism, single place)
- Removes the CI populate step and its "keep in sync" maintenance burden
- Matches the team's existing pytest ergonomics on both sides

**Cons**:
- Layer 2 runtime guard monkey-patches `builtins.open` during pytest runs
  (scoped to test lifecycle only; documented limitation for mmap / ctypes I/O)
- Submodule grows a small `pyproject.toml` dev-dep + `[tool.uv]` block
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
- **Marker decay**: `@pytest.mark.integration` is trivially missed by new
  contributors. A test added without the marker but asserting on private
  content silently ships. Enforcement via a linter gate is possible but
  reintroduces the complexity the marker was meant to avoid.
- **Submodule stays harness-coupled**: the private repo still has no
  independent test suite. A future non-Python harness (MS Agent Framework,
  Go/Rust consumer) cannot validate the persona contract without re-
  implementing the Python import path.
- **CI populate step + fixture-sync burden persists**: every structural
  change to the real submodule still requires a matching change to the
  public fixture, and the divergence window (local passing / CI failing,
  or vice versa) remains open.
- **Integration tests still live in public `git log`**: while both Approach
  1 and Approach 2 leave pre-change assertions in pre-change history, only
  Approach 1 moves *new* private-coupled tests out of the public repo
  going forward. Approach 2 keeps the public-repo history accumulating
  private assertions under a differently-named directory.

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

**Approach 1** — repoint + two-layer guard + self-contained submodule
pytest.

Confirmed during discovery (Gate 1, 2026-04-13) and refined by Round 1
multi-reviewer convergence (also 2026-04-13):

- **Enforcement mechanism**: two layers wired into pytest via
  `tests/conftest.py`. Layer 1 is a collection-time substring scan; Layer 2
  is a runtime filesystem guard that patches `Path.open` / `read_text` /
  `read_bytes` / `builtins.open` to reject reads under
  `personas/<forbidden-name>/`. Both layers read from a single deny-list
  config in `tests/_privacy_guard_config.py`.
- **Submodule toolchain**: pytest with a `pyproject.toml` in
  `personas/personal/` declaring pytest + PyYAML as dev deps, plus a
  `[tool.uv]` block declaring the directory as a non-package with empty
  workspace members so `uv` does not reuse the parent venv.
- **Self-containment proof**: a fresh-venv test run in
  `scripts/verify-submodule-standalone.sh`, plus a positive runtime
  assertion that `importlib.import_module("assistant")` raises
  `ImportError` inside the submodule suite.
- **Scope**: covers both `personas/personal/` *and* `personas/work/` from
  day one, future-proofing for P6 (`work-persona-config`).
- **CI cleanup**: the `populate personas/personal from test fixture` step
  introduced in `76a313e` is **removed** — the conftest repoint makes it
  redundant. A new workflow-hygiene test
  (`tests/test_ci_workflow_hygiene.py`) prevents future workflows from
  silently re-introducing the dependency.
- **Cross-repo push**: a dedicated `scripts/push-with-submodule.sh` wrapper
  handles the dual-commit sequence (submodule push → parent gitlink
  update) atomically with a documented recovery story for partial-failure
  states.

Approaches 2 and 3 are not selected:

- **Approach 2 (marker-based dual-mode)** — markers decay, the submodule
  stays harness-coupled, and the CI populate-step / fixture-sync burden
  persists. See the approach's Cons section above for the full
  (Round-1-corrected) reasoning.
- **Approach 3 (env-var placeholders)** — over-engineered. Personas are
  private, not secret; refactoring every consumer of `PersonaRegistry` and
  `RoleRegistry` to load prompts from env vars is disproportionate to the
  problem.

### Changes from Round 1 review

- **Dropped**: the `FORBIDDEN_CONTENT_STRINGS` deny-list. Cross-confirmed
  by three reviewers: the strings the public repo can enumerate are the
  same strings that exist in the public fixture, so a content-based
  deny-list is incoherent. The path-based check is the full closure.
- **Added**: the Layer-2 runtime filesystem guard, the fresh-venv
  submodule-isolation proof, `[tool.uv]` workspace boundary, workflow-
  hygiene regression test, atomic push script, `ALLOW_STANDALONE_SUBMODULE_SKIP`
  opt-in for submodule standalone runs, and a fixture-sentinel-based
  replacement for the lost end-to-end composition test.
- **Reordered**: Phase 2 scrubs public tests *before* enabling the guard,
  otherwise the guard would fail collection on the unscrubbed baseline.
- **Tightened**: work-package scopes, dependencies, and constraints to
  close routing gaps (`wp-integration` now declares
  `requires_private_repo_write`; `wp-ci-cleanup` now depends on
  `wp-public-tests`; `wp-integration` deny-lists submodule content so it
  cannot accidentally write there).
