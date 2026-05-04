# Gotchas

Running list of subtle traps we've hit and how to avoid them. Add to this
file when future proposals discover new ones — cheaper than re-learning.

## G1. GitHub Actions silently ignores workflows with unquoted `on:` key

**Symptom**: Workflow file is committed at `.github/workflows/ci.yml`,
Actions is enabled, the YAML parses successfully, but the workflow never
runs and doesn't appear in the repo's Actions tab or in
`gh workflow list`. No error, no UI notification.

**Root cause**: YAML 1.1 (which PyYAML and most tooling uses by default)
lists `on`, `off`, `yes`, `no`, `true`, `false` all as boolean literals. An
unquoted top-level key `on:` is parsed as the boolean `true`, so the
workflow document becomes `{name: "CI", true: {...}, jobs: {...}}`. GitHub
Actions looks for the literal key `on`, doesn't find one, and silently
skips the workflow — no registration, no trigger. YAML 1.2 fixed this (only
`true`/`false` are booleans), but most of the toolchain still uses 1.1.

**Fix**: quote the key.

```yaml
# BROKEN (parses as {true: ...}, Actions silently ignores):
on:
  push:
    branches: [main]

# OK (parses as {on: ...}):
"on":
  push:
    branches: [main]
```

**How to detect**: `python -c "import yaml; print(list(yaml.safe_load(open('.github/workflows/ci.yml')).keys()))"` — if you see `'true'` instead of `'on'` in the output, you have this bug.

**Prevention**: always quote the `"on":` key in any GitHub Actions workflow
you write. Also applies to any YAML-configured system that cares about
literal string keys (not just GitHub Actions).

---

## G2. Tests that depend on `personas/<name>/` fail on CI when the submodule is private

**Symptom**: Tests pass locally, fail on CI with
`ValueError: Persona 'personal' not found or not initialized. Available: []`
across ~20+ tests. 5 more tests error with the same root cause in their
fixture setup.

**Root cause**: `personas/<name>/` is a git submodule mounted from a
private repo. The CI workflow checks out the outer repo with
`submodules: false` because CI cannot authenticate to the private submodule
origin. So on CI, `personas/personal/` exists as an empty directory; the
`persona.yaml` file tests expect is missing. `PersonaRegistry.discover()`
returns `[]`, and `PersonaRegistry.load("personal")` raises. Any test
touching the real persona fails.

**Fix**: ship a fixture under `tests/fixtures/personas/personal/` that
mirrors the submodule's contents (redacted if the real submodule has
secrets — in our case it has none, only env-var references), and populate
`personas/personal/` from the fixture as a CI step before running pytest.

```yaml
# In .github/workflows/ci.yml, before pytest:
- name: Populate test persona fixture
  run: |
    mkdir -p personas/personal
    cp -R tests/fixtures/personas/personal/. personas/personal/
```

Locally, the submodule overlays the fixture so real behavior is preserved.
CI gets a self-contained baseline.

**Alternative** (not used): store a PAT as a CI secret and checkout with
`submodules: recursive`. Rejected because it ties CI to a human-owned
token, adds rotation burden, and requires keeping the fixture in sync with
the real submodule anyway (for local smoke without `git submodule update
--init`).

**Prevention**: whenever a new proposal adds tests that depend on submodule
content, also add the corresponding files under `tests/fixtures/` and
extend the CI populate step.

---

## G3. `uv_build` rejects packages without an `__init__.py`

**Symptom**: `uv sync` fails with
`Failed to build assistant: Expected a Python module at: src/assistant/__init__.py`
even though the src/ tree otherwise looks complete.

**Root cause**: `uv init --package` scaffolds `src/<name>/__init__.py`. If
you delete the auto-generated `__init__.py` intending to write your own
module structure later, `uv_build` fails to recognize the package during
the very next `uv sync`.

**Fix**: always ensure `src/<package>/__init__.py` exists (it can be empty
or contain only a docstring + `__version__`) before running `uv sync`.

**Prevention**: don't delete the scaffolded `__init__.py`; edit it.

---

## G4. `unittest.mock.patch()` can't find lazily-imported attributes

**Symptom**: Test raises
`AttributeError: <module 'foo'> does not have the attribute 'bar'` when
patching a dependency that's imported inside a function body.

**Root cause**: `patch("foo.bar")` looks up `bar` as an attribute of the
already-loaded module `foo`. If the real `from lib import bar` happens
inside a function (lazy import), `foo.bar` doesn't exist until that
function runs. Lazy imports are common as a "cold start" optimization but
they break mock-based tests.

**Fix**: either move the import to module top-level, or patch at the source
module (`patch("lib.bar")`) if the caller imports with
`from lib import bar` — but the first form is usually clearer.

**Trade-off**: top-level imports pull heavier dependencies at module load.
Usually fine; reserve lazy imports for genuinely optional deps behind
`[extras]`.

---

## G5. OpenSpec strict validator wants SHALL/MUST near the top of a Requirement body

**Symptom**: `openspec validate --strict` errors with
`Requirement "Foo Bar" must contain SHALL or MUST` even though the body
contains `SHALL` inside a sub-clause starting with "When X, the system
SHALL Y".

**Root cause**: the validator scans for the normative keyword in the
opening sentence of the requirement body. If the first clause is
conditional ("When...") the keyword may come too far down.

**Fix**: rewrite so the requirement body's first clause leads with
`The system SHALL ...` or `The <subsystem> MUST ...`. Move any "when"
qualifiers after.

```markdown
### Requirement: Foo

# WRONG (SHALL is buried):
When a user requests X, the system SHALL do Y.

# OK:
The system SHALL do Y when a user requests X.
```

---

## G6. Private-persona content leakage via public test assertions

**Symptom**: One of:
1. CI passes locally but private content (prompt strings, role-override
   phrasing) appears verbatim in public test code, or shows up in `git log`
   diffs against the public repo.
2. A test fails at collection with `_PrivacyBoundaryViolation` (subclass
   of `pytest.UsageError`) naming a forbidden `personas/<name>/` path.
3. CI passes but the fixture and the real submodule have diverged and
   nobody noticed until local runs surface a shape mismatch.

**Root cause**: two failure classes, both caught by the two-layer guard:

1. **Literal-path leak** — a public test file contains the substring
   `personas/personal/` or `personas/work/` (in an assertion, a path
   literal, or even a docstring comment). Layer 1's collection-time
   substring scan (`tests/conftest.py`) catches this.
2. **Constructed-path leak** — a test builds a forbidden path via join
   idioms like `Path("personas") / name / "persona.yaml"` where `name`
   comes from a variable, parameter, or env lookup. The substring scan
   cannot see this (no literal appears in source). Layer 2's runtime FS
   guard (`tests/_privacy_guard_plugin.py`) catches it by patching
   `pathlib.Path.open`, `Path.read_text`, `Path.read_bytes`,
   `builtins.open`, `os.open`, and `subprocess.Popen.__init__` — any
   read or subprocess argv that resolves under `personas/<forbidden>/`
   raises `_PrivacyBoundaryViolation` at the moment of call.

Common upstream cause: `personas_dir` fixture in `tests/conftest.py` was
(re-)pointed at `REPO_ROOT / "personas"` instead of
`REPO_ROOT / "tests" / "fixtures" / "personas"`, so every consumer of
the fixture now reads the real submodule.

**Fix**:

```python
# tests/conftest.py — correct:
@pytest.fixture
def personas_dir() -> Path:
    return REPO_ROOT / "tests" / "fixtures" / "personas"

# tests/conftest.py — WRONG (resurrects the leak):
@pytest.fixture
def personas_dir() -> Path:
    return REPO_ROOT / "personas"
```

- Rewrite assertions to use fixture-defined values (e.g. the
  `FIXTURE_PERSONA_SENTINEL_v1` marker in the fixture prompt) rather than
  strings lifted from the real submodule.
- If a test genuinely needs to validate real submodule data, it does not
  belong in the public `tests/` tree — relocate it to
  `personas/<name>/tests/` as a self-contained test (no imports from
  `src/assistant/*`, YAML parsed via `yaml.safe_load`). See D3/D4 in
  `openspec/changes/test-privacy-boundary/design.md`.

**How to detect**: run `uv run pytest tests/` from a clean checkout with
the submodule deinitialized (`git submodule deinit -f personas/personal`).
If the suite passes, the boundary is intact. If anything fails with a
missing `personas/<name>/persona.yaml`, you have a leak. The wrapper
`scripts/verify-public-tests-standalone.sh` automates this safely (uses
`trap` to restore the submodule on exit).

**Prevention**: the two-layer guard in `tests/conftest.py` +
`tests/_privacy_guard_plugin.py` catches both literal and
constructed-path leaks at collection/runtime, reading its deny-list
(`FORBIDDEN_PATH_NAMES = ("personal", "work")`) from
`tests/_privacy_guard_config.py`. The guard also covers `work` from day
one even though `personas/work/` is not yet populated.

**Known out-of-coverage surface** (per design R2 —
`openspec/changes/test-privacy-boundary/design.md`): the runtime guard
does NOT see (a) `mmap.mmap` on an already-opened file descriptor, (b)
`ctypes`-based I/O bypassing the stdlib entirely, (c) `os.system` on
Windows (it dispatches through `cmd.exe`, not `subprocess.Popen`), or
(d) deliberately-split subprocess argv where the forbidden substring is
reconstructed only after `execve` (e.g. `['sh', '-c', f'cat
personas/{name}/x']` with `name` obtained from an env var read at
subprocess time). These are outside the documented threat model
(deliberate evasion, not accidental Copilot idiom). Layer 1's substring
scan is the only defense for any of these patterns, so keep forbidden
literals out of test source entirely — use dynamic needle construction
(`tuple(f"personas/{n}/" for n in FORBIDDEN_PATH_NAMES)`) in any file
that legitimately needs to reference the deny-list as data.

**The `ASSISTANT_PERSONAS_DIR` env var.** `tests/conftest.py` sets this
via `os.environ.setdefault` so every in-process `PersonaRegistry` /
`RoleRegistry` (including the one `cli.py` builds when tests invoke
`assistant -p personal`) honors the fixture root. CI also sets it at
the job level as defense-in-depth. Precedence is
`explicit constructor arg > env var > Path("personas") default` — this
contract is locked by `tests/test_env_var_contract.py`, which every
change to `PersonaRegistry`/`RoleRegistry` constructors must keep green.
The env var is an implementation detail enabling the repoint, not a
public configuration surface; production callers should leave it unset.

---

## G7. Submodule test standalone mode silent-skip

**Symptom**: A submodule maintainer runs
`cd personas/personal && pytest tests/` in isolation (without a parent
checkout), the suite reports green, and the maintainer pushes. Later, a
full parent-checkout run fails: a role override in the submodule
references a base role that does not exist in the parent `roles/`
directory, breaking composition.

**Root cause**: `personas/personal/tests/test_role_overrides.py` used to
resolve the parent roles directory via
`Path(__file__).resolve().parents[2] / "roles"`. When the submodule is
checked out standalone (not inside a parent), that path does not exist,
and an earlier draft silently skipped the existence check. Silent-skip
converted a real invariant violation into a false green.

**Fix**: the check now `pytest.fail`s by default with a message naming
the required env var. Setting `ALLOW_STANDALONE_SUBMODULE_SKIP=1`
converts the failure to an explicit `pytest.skip` with a loud message —
an opt-in acknowledging "I know this run does not validate the cross-repo
invariant":

```bash
# Default (strict): fails loudly if parent roles/ unreachable
cd personas/personal && pytest tests/

# Explicit opt-in for standalone runs (skip with loud message):
ALLOW_STANDALONE_SUBMODULE_SKIP=1 pytest tests/
```

**How to detect**: if `pytest tests/` in the submodule reports
`SKIPPED [1] test_role_overrides.py: parent roles/ not reachable...`
**without** the env var set, the strict mode is broken — file a bug
against the submodule. If the env var is set, that single skip line is
expected and announces itself clearly.

**Prevention**: default is strict; the env var is documented here (G7),
in the submodule's own README, and in the failure message itself so
maintainers always know the exact incantation to bypass. The parent-repo
run never sets this env var, so the cross-repo invariant is exercised
every time the full suite runs from a parent checkout.


## G8. Local `mypy src/` passes while CI `mypy src tests` fails

**Symptom**: Pre-push gates green on your machine. CI red on the mypy
step, with errors only in test files like `"None" not callable` on
`StructuredTool.coroutine(...)` or `"dict[str, Any]" not callable` on
`args_schema(**kwargs)`.

**Root cause**: The repo's CI workflow runs:
```yaml
- name: Mypy
  run: uv run mypy src tests
```
…checking both source and test trees. A local convenience invocation of
`uv run mypy src/assistant/` (or just `mypy src/`) only checks the
source tree, so test-side type errors stay hidden until CI runs.

Common culprits in tests:
- LangChain types `StructuredTool.coroutine` as `Coroutine | None` and
  `args_schema` as `type[BaseModel] | dict | None`. Direct
  `tool.coroutine(...)` or `tool.args_schema(**kwargs)` call sites
  fail mypy narrowing.
- `type: ignore[code]` comments that were valid at write-time become
  `unused-ignore` errors after a library update changes stub precision.

**Solution**: Always run the full CI scope locally before pushing:

```bash
uv run mypy src tests   # matches CI
uv run ruff check src tests
uv run pytest tests/
```

For LangChain `StructuredTool` handling in tests, use typed helpers
that assert-then-narrow:

```python
def _call(tool: Any, **kwargs: Any) -> Any:
    assert tool.coroutine is not None
    return tool.coroutine(**kwargs)

def _instantiate_args(tool: Any, **kwargs: Any) -> BaseModel:
    schema_cls = tool.args_schema
    assert isinstance(schema_cls, type) and issubclass(schema_cls, BaseModel)
    return schema_cls(**kwargs)
```

Caught during `/cleanup-feature http-tools-layer` when 15 test-side
mypy errors landed only on CI — cost one CI cycle. The Landing the
Plane checklist in `CLAUDE.md` now enumerates the full CI scope so
local gates match remote.

## G9 — `Extension.health_check()` widened from `bool` to `HealthStatus` (P9 error-resilience)

The `Extension` Protocol previously declared `async def health_check(self) -> bool`.
After P9 (`error-resilience`), it is `async def health_check(self) -> HealthStatus`.

This is a hard protocol break. All seven internal stubs were updated atomically
in the same change. **Out-of-tree extensions** (private persona submodules) that
defined their own `Extension`-compatible class will need a one-line migration:

```python
from assistant.core.resilience import default_health_status_for_unimplemented

class MyExtension:
    name = "my-extension"

    async def health_check(self) -> HealthStatus:
        return default_health_status_for_unimplemented(self.name)
```

If the extension already has a real backend probe, return a populated
`HealthStatus(state=HealthState.OK | DEGRADED | UNAVAILABLE, ...)`. The
helper `health_status_from_breaker(breaker, key=f"extension:{self.name}")`
maps a `CircuitBreaker` to a `HealthStatus` automatically.

**Why no deprecation shim**: dual-return-type protocols defeat mypy at the
boundary. The persona registry installs a runtime conformance guard (D11)
that raises `TypeError` with the migration recipe on the first non-conforming
probe, so a private extension that was missed produces a clear, actionable
error rather than silent degradation.
