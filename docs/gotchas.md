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
