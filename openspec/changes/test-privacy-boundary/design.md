# Design: test-privacy-boundary

## Context

The public repo contains persona-consuming test code; the private repo (the
`personas/personal/` submodule) contains persona *data*. The current
`tests/conftest.py` resolves `personas_dir` to `REPO_ROOT / "personas"`, which
points at the submodule mount. Public tests can therefore read private data
and encode private content as assertions. This change repartitions testing
along the existing privacy seam rather than introducing a new abstraction.

Round 1 review surfaced that an earlier draft of this design relied on a
`FORBIDDEN_CONTENT_STRINGS` deny-list. That approach was incoherent: the
strings the public repo can enumerate are exactly the strings that already
exist in the public fixture (e.g. `"Personal Persona Context"` lives in
`tests/fixtures/personas/personal/prompt.md`), so a deny-list keyed on them
would block legitimate fixture-based assertions while still missing any
truly-private string the public repo cannot see. The design now drops the
content-string approach entirely and treats **path-based enforcement as the
sole authoritative signal**, with two enforcement layers (substring scan as
collection-time advisory + runtime filesystem guard as authoritative).

## Goals

- **G1**: Public tests must run to green without the private submodule being
  populated.
- **G2**: Any attempt to introduce a path-based reference to
  `personas/personal/` or `personas/work/` from public `tests/` must fail —
  loudly, at collection time when the reference is a literal substring, and
  at runtime when the reference is constructed via path-join idioms.
- **G3**: The `personas/personal/` submodule must own its own test suite
  that runs *without `assistant` being importable*, so the persona data is
  reusable by a non-Python consumer.
- **G4**: The CI workaround (commit `76a313e`) must be removed, eliminating
  the "keep fixture in sync with submodule" maintenance burden.

## Non-goals

- **NG1**: This change does not alter `PersonaConfig`, `PersonaRegistry`,
  `RoleConfig`, or `RoleRegistry` semantics. It only changes what directory
  those classes read from in public tests.
- **NG2**: This change does not introduce a generic "redaction" or
  secrets-management layer for persona content. Personas are private, not
  secret.
- **NG3**: This change does not populate `personas/work/`. P6
  (`work-persona-config`) remains the home for that work.
- **NG4**: The boundary guard scope is the public `tests/` tree only.
  `openspec/changes/<id>/specs/*.md` and `docs/*.md` may name forbidden
  paths or strings for documentation purposes — they are not collected by
  pytest and not under the guard.
- **NG5**: This change does not enumerate "private content strings". The
  public repo cannot know what is private inside the submodule; trying to
  list private strings is a category error. Path-based enforcement is the
  full closure.

## Key decisions

### D1: Two-layer guard — substring scan + runtime FS guard

**Decision**: Enforcement runs as **two layers** wired into pytest:

- **Layer 1 (advisory, collection-time)**: A
  `pytest_collection_modifyitems` hook reads each collected test file's
  source text and emits a clear failure if it contains a forbidden path
  substring. Catches the obvious case quickly with a readable message
  before any test body runs.
- **Layer 2 (authoritative, runtime)**: A pytest plugin (registered via
  `tests/_privacy_guard_plugin.py` and loaded via `pytest_plugins` in
  `tests/conftest.py`) patches `pathlib.Path.open`, `pathlib.Path.read_text`,
  `pathlib.Path.read_bytes`, and `builtins.open` for the duration of test
  collection and execution. Any attempt to open a path that resolves under
  `personas/<name>/` (where `<name>` is in `FORBIDDEN_PATH_NAMES`) raises
  `_PrivacyBoundaryViolation`, which inherits from `pytest.UsageError`.
  Allow-listed read paths under `tests/fixtures/` and `personas/_template/`
  are permitted.

**Why**: Layer 1 alone cannot stop the standard
`Path("personas") / persona_name / "persona.yaml"` idiom — Copilot and
hand-written code routinely build paths that way and produce no matching
substring. Layer 2 catches *any* read attempt regardless of how the path
was constructed, because all reads ultimately funnel through `Path.open` /
`builtins.open`. Together they give fast feedback on the easy cases and
real coverage on the hard ones.

**Trade-off**: Layer 2 monkey-patches `builtins.open`, which is invasive.
Mitigation: the plugin only patches during pytest collection + run (not at
import time of unrelated modules), and it explicitly allows reads outside
the `personas/<name>/` namespace, so production code paths exercised by
tests are unaffected. The plugin lives in a single file and is small enough
to review in one sitting.

### D2: Path-based deny-list as module constants

**Decision**: The guard's deny-list and allow-list live as module constants
in `tests/_privacy_guard_config.py`:

```python
FORBIDDEN_PATH_NAMES = ("personal", "work")
ALLOWED_READ_PREFIXES = ("tests/fixtures/", "personas/_template/")
```

Both layers (substring scan and runtime FS guard) read from these constants
so the rules are defined once. The config module is *not* a conftest and is
not collected by pytest; it is imported by `tests/conftest.py` and the
runtime plugin.

**Why**: Single source of truth. Adding a new persona name (e.g. when P6
populates `personas/work/`) is a one-line change in one place. The config
module's own constants are not subject to the guard's substring scan
because the scan only inspects test files (`test_*.py` and `*_test.py`),
not arbitrary helper modules.

**Trade-off**: Earlier draft used a `FORBIDDEN_CONTENT_STRINGS` list of
private prompt phrases. **Removed.** Per Round 1 review (cross-confirmed by
three reviewers from different angles), the strings we could enumerate
("Personal Persona Context", "Personal Context Additions") are present in
the public fixture verbatim, so the deny-list would either flag legitimate
fixture-based assertions or be useless. The public repo cannot know which
strings are private inside the submodule; path-based enforcement is the
only enumerable signal we actually have. This is captured as NG5.

### D3: Submodule test suite parses YAML directly, not via `PersonaConfig`

**Decision**: `personas/personal/tests/` uses `yaml.safe_load` + dict-shaped
assertions. It does not import `assistant.core.persona.PersonaConfig`.

**Why**: The self-containment goal (G3). If these tests imported the parent
harness, they'd break the moment the submodule is consumed by a non-Python
agent harness (e.g. the future MS Agent Framework harness, or a Go/Rust
consumer). The data contract is the YAML shape, not the Python class — so
tests should validate the YAML shape.

**Trade-off**: Minor duplication of structural knowledge (the submodule
tests "know" that `database.url_env` should exist, which
`PersonaConfig.__init__` also knows). We accept this because the
alternative — coupling the submodule to a specific harness's dataclass — is
worse.

### D4: Submodule pyproject + venv isolation

**Decision**: `personas/personal/pyproject.toml` declares the minimum needed
for its own test suite: `pytest`, `pyyaml`. It also declares
`[tool.uv]` with `package = false` and an empty `workspace.members`, so
`uv` invoked from inside the submodule does **not** walk up to the parent
project and reuse its venv.

The submodule's standalone-proof verification (task 3.6) creates a
**fresh** venv (`uv venv` inside `/tmp/...` or `python -m venv`), installs
only `pytest` and `pyyaml`, and runs the submodule suite there. It does
**not** use `PYTHONPATH=/dev/null` (which has no effect on installed
packages).

The submodule suite includes a positive runtime check
(`tests/test_no_assistant_import.py`) that calls
`importlib.import_module('assistant')` inside `pytest.raises(ImportError)`.
A pure-grep check is insufficient — `__import__('assistant')` and
`importlib.import_module('assistant')` both bypass it.

**Why**: Earlier draft assumed that putting tests under `personas/personal/`
with their own pyproject would isolate them. Round 1 review (A1) showed
that `uv run pytest` invoked from inside the submodule will discover the
parent project root and reuse its venv unless an explicit workspace
boundary is declared. Without isolation, `import assistant` succeeds
silently and the self-containment claim is unverifiable.

**Trade-off**: Adds two short config blocks (`[tool.uv]` boundary, fresh-venv
verification step) to the submodule. Acceptable: the cost is small and the
alternative — believing self-containment without proving it — is worthless.

### D5: Parent-repo `roles/` resolved via `../../roles/` from submodule tests, with explicit standalone opt-in

**Decision**: When the submodule suite validates that a role override
references an existing base role, it resolves the base roles directory via
`Path(__file__).resolve().parents[2] / "roles"` (two levels up from
`personas/personal/tests/test_xxx.py` → parent repo's `roles/`).

If `../../roles/` does not exist, the affected test calls
`pytest.fail("parent roles/ not reachable; set ALLOW_STANDALONE_SUBMODULE_SKIP=1 to bypass")`
unless the env var `ALLOW_STANDALONE_SUBMODULE_SKIP=1` is set, in which
case the test is `pytest.skip`ed with a loud message.

**Why**: Round 1 review (A6) flagged that a silent skip mode lets broken
role overrides land — a contributor running the submodule standalone would
see green, push, and only discover the breakage when someone runs the full
parent. Requiring explicit opt-in for the weak mode keeps the strong
invariant on by default; the env var lets a submodule maintainer
explicitly acknowledge they're skipping the cross-repo check.

**Trade-off**: A submodule maintainer running tests purely inside the
submodule has to remember the env var. Mitigation: the failure message
includes the exact env var to set; the docs (G6 in `docs/gotchas.md`)
record it.

### D6: Remove CI populate step entirely, not leave it as a safety net

**Decision**: `.github/workflows/ci.yml` loses its populate-personas step.

**Why**: Leaving it in place creates a **silent divergence trap**: a
developer who accidentally reintroduces `REPO_ROOT / "personas"` into
`conftest.py` would have CI pass (because the populate step overlays the
fixture) but local runs against a real submodule might fail — or succeed
with stale content. Removing the step means any leak attempt fails loudly
in CI.

**Trade-off**: If the conftest guard is ever disabled or broken, CI has no
second line of defense. Accepted: the conftest guard is a pure-Python,
in-repo check with low failure surface; duplicating its intent in YAML adds
coordination overhead for negligible robustness gain.

### D7: Submodule changes ship as two commits with an atomic push wrapper

**Decision**: A reusable script
`scripts/push-with-submodule.sh` performs the dual-commit sequence
atomically: (1) verify parent is rebased onto `origin/main`, (2) commit
submodule-side changes inside `personas/personal/`, (3) push submodule, (4)
update parent gitlink and commit, (5) push parent. On failure of step 5
after step 3 has succeeded, the script logs the dangling submodule SHA and
the operator-recovery command (force-delete the dangling submodule branch
or open a ticket) without attempting automatic rollback.

**Why**: Round 1 review (A8) flagged the failure mode where submodule push
succeeds but parent push fails (network race, branch-protection drift), and
the inverse. A documented atomic wrapper centralizes the recovery story.
Also: parent-repo PR diff shows only the submodule SHA bump; reviewers
inspecting submodule content must check it out at the new SHA or be
pointed at the private-repo PR.

**Trade-off**: One additional script under `scripts/`. The script is
required for tasks 5.3a/5.3b; ad-hoc `git push` is no longer the documented
path.

### D8: `tests/fixtures/` allow-list is restricted to data files

**Decision**: The runtime FS guard's allow-list is `tests/fixtures/**/*` for
data files (`.yaml`, `.yml`, `.md`, `.json`, `.txt`) only. Python files
under `tests/fixtures/` are **not** allow-listed; if a `.py` file there
attempts to read `personas/personal/`, the runtime guard fires.
`tests/fixtures/__init__.py` (empty marker) is the sole exception.

**Why**: Round 1 review (A5) showed that bulk-allowing `tests/fixtures/`
opens a smuggling channel: a `tests/fixtures/loader.py` that imports +
re-exports real submodule content launders private data through a path
the substring guard treats as trusted. Narrowing the allow-list to data
files closes the channel.

**Trade-off**: A future contributor wanting a Python helper under
`tests/fixtures/` must put it elsewhere (e.g. `tests/_helpers/`). Minor;
documented in `docs/gotchas.md`.

### D9: Guard scope = test files + conftest, with self-exclusion

**Decision**: The Layer 1 (substring scan) inspects:
- All files matching `tests/**/test_*.py` and `tests/**/*_test.py`.
- All files matching `tests/**/conftest.py`.

It does **not** inspect:
- `tests/_privacy_guard_config.py` (definitions of the deny-list itself).
- `tests/_privacy_guard_plugin.py` (the runtime guard implementation).
- Files under `tests/fixtures/`.

**Why**: Round 1 review (A3, A4) raised that conftest fixtures are imported,
not collected, so a fixture returning a forbidden path bypasses a
collection-only scan. Including conftest in the scan closes that gap.
The two `_privacy_guard_*.py` files are explicitly excluded because they
are the deny-list's own implementation; if they were scanned, the guard
would self-trip on its own constants.

**Trade-off**: The exclusion list is now four files (two scanned, two
not). Mitigation: the exclusion is hard-coded in
`_privacy_guard_config.py` as a tuple, not configurable, so the surface
for "exclusion drift" is small.

## Risks

### R1: Submodule tests drift from fixture content

If someone updates the real `personas/personal/persona.yaml` but forgets to
update `tests/fixtures/personas/personal/persona.yaml`, public tests will
continue passing against the stale fixture while the real submodule changes
shape. The submodule's own test suite catches shape-drift inside the
private repo, but cross-checking *between* fixture and real submodule is
not enforced.

**Mitigation**: Add a `docs/gotchas.md` entry reminding developers that
fixture and submodule YAML are intentionally decoupled, and that structural
changes to either should be mirrored manually. Out of scope: an automated
parity test — that would reintroduce the private-content coupling we just
removed.

### R2: Layer 2 monkey-patching has scope/timing risks

The runtime FS guard patches `pathlib.Path.open`, `Path.read_text`,
`Path.read_bytes`, and `builtins.open`. If a parent-repo dependency reads
files using a non-stdlib I/O path (e.g. a C extension that bypasses
`builtins.open`), the runtime guard cannot see those reads.

**Mitigation**: For the consumer set we have (`yaml.safe_load`, `Path.open`,
`open()`, `read_text`/`read_bytes`), the patch surface is sufficient.
Document the limitation: tests that use mmap, ctypes-based I/O, or shell
subprocesses are outside Layer 2's coverage; for those, Layer 1's
substring scan is the only line of defense.

### R3: Submodule push requires private-repo write access

Implementation requires commit-and-push inside `personas/personal/`, which
is a private GitHub repo. Any agent executing this work must have
credentials for that remote.

**Mitigation**: Tasks 5.3a and 5.3b are split into separate work packages
(`wp-submodule-tests` for 5.3a; `wp-integration` for 5.3b). Both packages
declare `constraints.requires_private_repo_write: true`. If credentials
are unavailable, the dispatcher quarantines the package for operator
pickup rather than failing silently. Task 5.3-alt documents the manual
recovery path.

### R4: Future CI workflows could re-introduce dependency on populated mount

Removing the populate step (D6) silently breaks any future GitHub Actions
workflow that does `assistant -p personal --check` (or similar) and
expects `personas/personal/persona.yaml` to exist at the mount point.

**Mitigation**: Add a public test
`tests/test_ci_workflow_hygiene.py` (task 4.4 below) that scans every
`.github/workflows/*.yml` for references to `personas/personal/` or
`personas/work/` and fails if any are not paired with an explicit
copy-from-fixture step or a routing through the fixture path. Catches the
regression at the same single-point-of-enforcement the rest of this change
relies on.
