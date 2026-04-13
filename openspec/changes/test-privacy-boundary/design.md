# Design: test-privacy-boundary

## Context

The public repo contains persona-consuming test code; the private repo (the
`personas/personal/` submodule) contains persona *data*. The current
`tests/conftest.py` resolves `personas_dir` to `REPO_ROOT / "personas"`, which
points at the submodule mount. Public tests can therefore read private data
and encode private strings as assertions. This change repartitions testing
along the existing privacy seam rather than introducing a new abstraction.

## Goals

- **G1**: Public tests must run to green without the private submodule being
  populated.
- **G2**: Any attempt to introduce a reference to `personas/personal/` or
  `personas/work/` (or private-content strings) from within public `tests/`
  must fail at collection time, with a clear remediation message.
- **G3**: The `personas/personal/` submodule must own its own test suite
  that runs *without importing anything from `src/assistant/`*, so the
  persona data is reusable by a non-Python harness.
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

## Key decisions

### D1: Collection-time guard, not runtime guard

**Decision**: Enforcement runs as a `pytest_collection_modifyitems` hook that
reads each collected test file's source text and refuses to continue if it
contains a forbidden substring.

**Why**: The guard must fail **before** any test body executes, so a developer
who writes a leak locally gets immediate, unambiguous feedback. A runtime
guard (e.g., patching `Path.open` to deny reads under `personas/`) would only
fire during execution, producing confusing late failures and potentially
missing never-run code paths.

**Trade-off**: Collection-time source inspection is coarse — it matches on
substrings, not on AST-level semantics. A test that builds the forbidden path
via string concatenation (`"personas/" + "personal"`) would slip past. We
accept this because (a) the threat model is accidental leakage, not
adversarial circumvention, and (b) if such a test were written, the *content
string* deny-list (`"Personal Persona Context"` etc.) would catch its
assertions anyway.

### D2: Deny-list is configured, not hardcoded

**Decision**: The guard reads its path-prefix deny-list and private-content
string deny-list from a constant near the top of `tests/conftest.py`:

```python
FORBIDDEN_PATH_SUBSTRINGS = (
    "personas/personal/",
    "personas/work/",
)
FORBIDDEN_CONTENT_STRINGS = (
    "Personal Persona Context",
    "Personal Context Additions",
)
ALLOWED_PATH_SUBSTRINGS = (
    "personas/_template/",
    "tests/fixtures/",
)
```

**Why**: Keeps the rules one scroll away from any developer writing tests,
and makes it trivial to extend when new persona names or private prompt
phrases are introduced. Avoids pulling in a YAML/TOML config file for a
three-tuple of constants.

**Trade-off**: A new private string added to the personal persona's
`prompt.md` is not automatically added to the deny-list. This is accepted:
the canonical test-privacy signal is the *path* (which is enumerable);
content-string checking is a defense-in-depth against a small set of known
past offenders.

### D3: Submodule test suite parses YAML directly, not via `PersonaConfig`

**Decision**: `personas/personal/tests/` uses `yaml.safe_load` + dict-shaped
assertions. It does not import `assistant.core.persona.PersonaConfig`.

**Why**: The self-containment goal (G3). If these tests imported the parent
harness, they'd break the moment the submodule is consumed by a non-Python
agent harness (e.g. the future MS Agent Framework harness, or a Go/Rust
consumer). The data contract is the YAML shape, not the Python class — so
tests should validate the YAML shape.

**Trade-off**: Minor duplication of structural knowledge (the submodule tests
"know" that `database.url_env` should exist, which `PersonaConfig.__init__`
also knows). We accept this because the alternative — coupling the submodule
to a specific harness's dataclass — is worse.

### D4: Submodule's `pyproject.toml` declares pytest + PyYAML only

**Decision**: `personas/personal/pyproject.toml` declares the minimum needed
for its own test suite: `pytest`, `pyyaml`. No build system (`build-backend`
left out; this is not an installable package).

**Why**: Keeps the submodule minimal. No `src/`, no entry points, no packages
— just enough to let `uv run pytest` or `pytest` work when invoked inside the
submodule.

**Trade-off**: The submodule cannot be `pip install`ed or imported as a
Python package. This is correct: it's a *data* artifact, not a library.

### D5: Parent-repo `roles/` resolved via `../../roles/` from submodule tests

**Decision**: When the submodule suite validates that a role override
references an existing base role, it resolves the base roles directory via
`Path(__file__).resolve().parents[2] / "roles"` (two levels up from
`personas/personal/tests/test_xxx.py` → parent repo's `roles/`).

**Why**: Submodule tests are typically invoked from inside a parent checkout.
When run standalone (without a parent), the base-role check can degrade to a
warn-and-skip: if `../../roles/` does not exist, the relevant test is
`pytest.skip`ed with a clear message.

**Trade-off**: Standalone execution is less strict. Acceptable: standalone
mode is for smoke-testing the submodule's YAML shape; the strongest
invariants (base-role existence) are only meaningful in the parent checkout.

### D6: Remove CI populate step entirely, not leave it as a safety net

**Decision**: `.github/workflows/ci.yml` loses its populate-personas step.

**Why**: Leaving it in place creates a **silent divergence trap**: a
developer who accidentally reintroduces `REPO_ROOT / "personas"` into
`conftest.py` would have CI pass (because the populate step overlays the
fixture) but local runs against a real submodule might fail — or succeed with
stale content. Removing the step means any leak attempt fails loudly in CI.

**Trade-off**: If the conftest guard is ever disabled or broken, CI has no
second line of defense. Accepted: the conftest guard is a pure-Python,
in-repo check with low failure surface; duplicating its intent in YAML adds
coordination overhead for negligible robustness gain.

### D7: Submodule changes ship as two commits (parent + submodule)

**Decision**: The implementation commits submodule content inside the
submodule's own history, pushes to its remote, then updates the parent repo's
submodule pointer in a separate commit.

**Why**: That's how submodules work — a parent commit only records a SHA
reference. We can't "carry" submodule file changes in a parent-repo diff.

**Constraint on implementation**: The parent-repo PR's diff will show only
the submodule SHA bump for `personas/personal/`. Reviewers inspecting the
content must either check out the submodule at the new SHA or be pointed at
the private-repo PR. The `/validate-feature` + `/parallel-review-implementation`
steps downstream must handle this correctly — they'll need to clone the
submodule at the new SHA to review its tests.

## Risks

### R1: Submodule tests drift from fixture content

If someone updates the real `personas/personal/persona.yaml` but forgets to
update `tests/fixtures/personas/personal/persona.yaml`, public tests will
continue passing against the stale fixture while the real submodule changes
shape. The submodule's own test suite catches shape-drift inside the private
repo, but cross-checking *between* fixture and real submodule is not enforced.

**Mitigation**: Add a `docs/gotchas.md` entry reminding developers that
fixture and submodule YAML are intentionally decoupled, and that structural
changes to either should be mirrored manually. Out of scope: an automated
parity test — that would reintroduce the private-content coupling we just
removed.

### R2: Collection guard has false positives

A test that quotes the string `personas/personal/` inside a comment or
docstring (e.g., describing *why* a fixture path was changed) would trip the
guard.

**Mitigation**: The guard allow-list includes `tests/fixtures/`, so fixture
files can contain any content. For commentary in test files, recommend
contributors describe the rule in reference form (e.g., "the guard in
conftest.py rejects...") rather than quoting a path literal. If this proves
too restrictive in practice, upgrade the guard to AST-based inspection (skip
string literals inside `ast.Constant` nodes that are clearly comments or
module-level doctrings) as a follow-up — not in scope for this change.

### R3: Submodule push requires private-repo write access

Implementation requires commit-and-push inside `personas/personal/`, which is
a private GitHub repo. Any agent executing this work must have credentials
for that remote.

**Mitigation**: IMPLEMENT phase must be a single-agent (or co-located agents)
job for the `wp-submodule-tests` package. Cannot run in a vendor container
without the private-repo SSH key. Documented in `work-packages.yaml` as a
constraint.
