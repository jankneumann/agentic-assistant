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
  `tests/conftest.py`) patches the following I/O entry points for the
  duration of test collection and execution:
  - `pathlib.Path.open`, `pathlib.Path.read_text`, `pathlib.Path.read_bytes`
  - `builtins.open`
  - `os.open` (the canonical syscall choke point; `io.FileIO`,
    `codecs.open`, `io.open`, and `open()` all route through it)
  - `subprocess.Popen.__init__` (scans `args`/`argv` for forbidden path
    substrings, closing the "Copilot writes `subprocess.run(['cat', ...])`"
    bypass class — Round 2 finding B-N1)

  Any attempt to open/read a path that resolves under `personas/<name>/`
  (where `<name>` is in `FORBIDDEN_PATH_NAMES`), or to spawn a subprocess
  whose argv contains such a path literal or a string constructible as
  such (see Round 2 finding B-N1 for the bypass class this closes), raises
  `_PrivacyBoundaryViolation`, which inherits from `pytest.UsageError`.
  Allow-listed read paths under `tests/fixtures/` and `personas/_template/`
  are permitted.

  **Plugin self-probe (B-N8)**: At `pytest_configure` time, after installing
  the patches, the plugin opens a canary path under `personas/personal/`
  and asserts `_PrivacyBoundaryViolation` is raised. If the patches failed
  to install (e.g., future CPython refuses Python-level rebinding of a
  C-slot method), the self-probe fails loudly via `pytest.UsageError`
  before any real test runs. Prevents the silent-disable failure mode.

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
`[tool.uv]` with `package = false` and an empty `workspace.members`, and
pins `uv >= 0.5.0` in the fresh-venv verification script because the
`[tool.uv].package` field semantics stabilized at that version (Round 2
finding B-N6).

The submodule's standalone-proof verification (task 3.6) creates a
**fresh** venv (`python -m venv` with the script's own Python
interpreter), installs only `pytest` and `pyyaml` with pinned minimums,
and runs the submodule suite there. The script `cd`s into
`personas/personal/` before invoking pytest so the submodule's pyproject
is pytest's rootdir, not the parent's — otherwise the parent's
`pytest_plugins` (the privacy guard) would be loaded and could fire on
legitimate submodule reads (Round 2 finding B-N7). It does **not** use
`PYTHONPATH=/dev/null` (which has no effect on installed packages).

The submodule suite includes a positive runtime check
(`tests/test_no_assistant_import.py`) that calls
`importlib.import_module('assistant.core.persona')` — NOT just
`importlib.import_module('assistant')` — inside `pytest.raises(ImportError)`.
The qualified path is distinctive to this project and will not collide
with the unrelated PyPI package named `assistant` that a contributor
could have pip-installed for other work (Round 2 finding B-N5). A
pure-grep check is insufficient — `__import__` and
`importlib.import_module` both bypass it.

**Forward-compatibility guard**: A parent-repo test
(`tests/test_workspace_hygiene.py`, added alongside the workflow-hygiene
test in Phase 4) asserts that the parent `pyproject.toml` does NOT
declare `[tool.uv.workspace]` with `personas/*` as a member. If someone
later adds `members = ['personas/*']` for dev ergonomics, the submodule's
own `workspace.members = []` cannot override inclusion (membership is
declared by the workspace root, not the member). The guard catches this
regression class explicitly (Round 2 finding B-N6).

**Why**: Earlier draft assumed that putting tests under `personas/personal/`
with their own pyproject would isolate them. Round 1 review (A1) showed
`uv run pytest` from inside the submodule would reuse the parent venv
without an explicit workspace boundary. Round 2 review (B-N5, B-N6, B-N7)
further found that (a) the `assistant` PyPI package name could collide
with an unrelated install and make the positive-import assertion
misleading, (b) the workspace boundary is one-directional — parent-
declared membership overrides member-declared `workspace.members = []`,
so a future parent change could silently reintroduce the leak, and (c)
pytest's rootdir discovery from parent cwd could load parent plugins
against submodule tests.

**Trade-off**: Adds several short config blocks (version pin, workspace
forward-compat guard, cd-before-pytest in the verification script) to
the submodule + parent. Acceptable: each one closes a concrete gap
Round 1/2 surfaced, and the cost is small.

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

**Additional rule (Round 2 finding B-N4)**: The test files that legitimately
need to reference forbidden path substrings — specifically
`tests/test_ci_workflow_hygiene.py` (which greps workflow YAML for
leakage) and `tests/test_workspace_hygiene.py` (which greps the parent
pyproject for `personas/*` workspace membership) — SHALL **not** use
the substring as a literal in their source. Instead, they SHALL import
`FORBIDDEN_PATH_NAMES` from `tests/_privacy_guard_config.py` and
construct the needle dynamically:

```python
from tests._privacy_guard_config import FORBIDDEN_PATH_NAMES
needles = tuple(f"personas/{name}/" for name in FORBIDDEN_PATH_NAMES)
```

This keeps the test file free of forbidden literals (so Layer 1 doesn't
self-trip) and auto-extends when new persona names are added to the
deny-list. Belt-and-suspenders: the hygiene-test filenames are **also**
added to the Layer 1 exclusion list, so a literal substring slipping
back in during future maintenance still doesn't cause a hard session
failure — it fails the hygiene test's own assertion instead, with a
better diagnostic.

**Why**: Round 1 review (A3, A4) raised that conftest fixtures are imported,
not collected, so a fixture returning a forbidden path bypasses a
collection-only scan. Including conftest in the scan closes that gap.
Round 2 review (B-N4) raised that the hygiene-test files need the
forbidden substring as *data* for their own scanning logic; a naive
implementation would self-trip Layer 1. The dynamic-needle pattern
resolves it cleanly.

**Trade-off**: The exclusion list is now six files (test_*.py and
conftest.py scanned; `_privacy_guard_config.py`,
`_privacy_guard_plugin.py`, `test_ci_workflow_hygiene.py`,
`test_workspace_hygiene.py` excluded). Mitigation: the exclusion is
hard-coded in `_privacy_guard_config.py` as a tuple, not configurable,
so the surface for "exclusion drift" is small.

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
`Path.read_bytes`, `builtins.open`, `os.open`, and
`subprocess.Popen.__init__`. After Round 2 finding B-N2, `os.open` is
the canonical syscall-level choke point covering `io.FileIO`,
`codecs.open`, `io.open`, and higher-level wrappers. After Round 2
finding B-N1, `subprocess.Popen.__init__` catches the
`subprocess.run(['cat', path])` bypass class by scanning argv elements
for forbidden substrings.

**Remaining out-of-coverage surface**:
- **mmap.mmap** on an already-opened file descriptor: if a test opens a
  file (which Layer 2 would catch) and mmaps it, the mmap read is
  invisible. Already-opened-then-mmap requires first getting past the
  open patch, so this is low-risk.
- **ctypes-based I/O** bypassing the stdlib entirely. Rare in tests.
- **os.system** and **os.popen** (both use the shell). Layer 2 does
  patch `subprocess.Popen` and `os.system` dispatches through it on
  POSIX, but on Windows `os.system` calls `cmd.exe` directly. Document
  this as a known gap; `os.system` is rare in modern test code.
- **Subprocess argv with a forbidden path split across multiple argv
  elements** (e.g. `cat personas/personal/persona.yaml` might be
  `['cat', 'personas/personal/persona.yaml']` — caught — but a
  sufficiently-motivated reconstruction like
  `['sh', '-c', f'cat personas/{name}/x']` with `name = "personal"`
  obtained via an environment variable at subprocess time is
  uncatchable at argv-inspection time). Accepted: this crosses from
  "accidental Copilot idiom" into "deliberate evasion", outside the
  documented threat model.

**Mitigation**: Document these gaps explicitly in
`docs/gotchas.md` G6 so future contributors know which I/O patterns are
structurally unsupervised. Layer 1's substring scan remains the only
line of defense for those cases, and catches any literal
`personas/personal/` appearance regardless of the I/O style.

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
