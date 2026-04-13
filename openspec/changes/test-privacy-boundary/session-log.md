# Session Log — test-privacy-boundary

---

## Phase: Plan (2026-04-13)

**Agent**: claude-opus-4-6 (main / autopilot) | **Session**: N/A

### Decisions

1. Selected Approach 1 — repoint fixture root, add a conftest guard, and
   relocate persona-specific tests into the submodule. This matches the user
   requirement that the persona repo stay harness-agnostic so it can later be
   consumed by a non-Python harness.

2. D1. Enforce the boundary at pytest collection time. A hook inspects each
   collected test file and fails the session before any test body runs.
   Substring matching is intentional; AST inspection is out of scope.

3. D2. Deny-lists live as module constants near the top of conftest.py, so
   the rules are discoverable by every test author without a separate config
   file.

4. D3. Submodule tests parse YAML directly via yaml.safe_load. They do not
   import from the parent harness. This preserves the self-contained goal.

5. Scope covers both the personal persona and the future work persona.
   Guard deny-list includes both path prefixes on day one, even though the
   work submodule is not yet populated.

6. D6. Remove the CI populate step rather than keep it as defense in depth.
   Keeping it creates a silent-divergence trap between fixture content and
   real submodule content.

### Alternatives Considered

- Approach 2, marker-based dual-mode — rejected as cosmetic. Moving private
  strings under tests/integration still leaves them in the public repo's
  git log, so the leak is not actually fixed.
- Approach 3, env-var placeholders — rejected as over-engineered. Personas
  are private, not secret; refactoring every consumer of the registries to
  load content from env vars is disproportionate.
- CI lint instead of conftest hook — rejected in favor of the hook so local
  feedback is fast.
- Keeping the CI populate step as a safety net — rejected per D6.

### Trade-offs

- Accepted substring matching over AST inspection because the threat model
  is accidental leakage, not adversarial circumvention.
- Accepted a two-dep pyproject addition (pytest, pyyaml) in the submodule to
  preserve self-containment. Coupling the submodule to the parent harness
  would cost more in the long run.
- Accepted that standalone submodule execution may skip the base-role
  existence check when the parent roles dir is not reachable. Acceptable
  because strong cross-repo invariants only hold in a parent checkout.

### Open Questions

- [ ] How does /implement-feature route the submodule-tests package to an
  agent with private-repo write access? work-packages.yaml uses a
  non-standard constraints.requires_private_repo_write flag.
- [ ] Should a later change add a fixture-vs-submodule parity check, or keep
  the two intentionally decoupled? Defer until drift is observed.

### Context

Goal of this phase was to scope a change that prevents private persona data
from leaking through the public test suite. Artifact outputs cover proposal,
design, spec delta, tasks, contracts stub, and work packages. openspec
validate --strict passes. Coordinator registration returned HTTP 403 on the
local profile API key; recorded as a permissions degradation, not a blocker.

---

## Phase: Plan Review Round 1 (2026-04-13)

**Agent**: claude-opus-4-6 (3 parallel reviewer subagents) | **Session**: N/A

### Summary

Three independent reviewers (architecture/spec, adversarial, implementation
feasibility) produced 27 total findings: 7 BLOCKING, 13 MAJOR, 7 MINOR/NIT.
Cross-reviewer agreement on three foundational issues triggered a design-
level rewrite rather than a mechanical patch.

### Convergent findings (cross-reviewer confirmation)

- **Content-string deny-list is misframed** (I2 + A2 + A9). The strings
  "Personal Persona Context" and "Personal Context Additions" already
  exist in the public fixture; the deny-list would block legitimate
  assertions without preventing any actual leak. **Action**: removed the
  content deny-list entirely; path-based enforcement becomes the sole
  authoritative signal (now NG5). The guard's failure-message policy
  also updated to avoid echoing private payloads into CI logs.

- **Substring path-matching has a Copilot-friendly bypass** (A2). The
  idiom `Path("personas") / name / "x.yaml"` produces no matching
  substring. **Action**: added Layer 2 — a runtime filesystem guard as a
  pytest plugin that patches `Path.open`, `read_text`, `read_bytes`, and
  `builtins.open` to reject reads under `personas/<forbidden-name>/`.
  Design D1 rewritten to describe the two-layer architecture.

- **Submodule self-containment not verifiable as drafted** (A1).
  `uv run pytest` from inside the submodule reuses the parent venv where
  `assistant` IS importable; `PYTHONPATH=/dev/null` has no effect on
  installed packages; the grep misses `importlib.import_module` and
  `__import__`. **Action**: D4 rewritten to require (a) `[tool.uv]`
  workspace boundary in the submodule pyproject, (b) a fresh-venv
  standalone-proof in `scripts/verify-submodule-standalone.sh`, and
  (c) a positive runtime assertion that `import assistant` raises
  ImportError.

### Other BLOCKING fixes

- **Phase 2 ordering was circular** (I1): guard implementation preceded the
  scrub of existing forbidden strings, so the guard's own verification
  runs would fail collection. Phase 2 reordered: scrub 2.4-2.8 precedes
  guard implementation 2.10-2.14.
- **Root pytest does not run submodule tests** (F1): `pyproject.toml`
  pins `testpaths = ["tests"]`. Task 5.2 split into 5.2a (root pytest)
  and 5.2b (dedicated script runs submodule suite).
- **wp-public-tests deny blocks its own verification** (F2): deny on
  `personas/personal/**` conflicted with task 2.9's submodule manipulation.
  Task 2.9 rewritten to use `git submodule deinit`/`update --init` via a
  `trap`-protected script (I5), and the deny narrowed to specific paths
  that wp-public-tests doesn't legitimately touch.
- **Guard scope ambiguity** (A3, A4): scope now explicitly includes
  `tests/**/conftest.py`, excludes `tests/_privacy_guard_config.py` and
  `_privacy_guard_plugin.py`, and the `tests/fixtures/` allow-list is
  narrowed to data-file types (D8).

### Other MAJOR fixes

- **Lost compose_system_prompt end-to-end coverage** (F4): added task 2.3
  (fixture-sentinel-based integration test) and task 2.1 (add sentinel
  string to fixture).
- **wp-integration missing `requires_private_repo_write`** (F5, I3):
  added the constraint; task 5.3 split into 5.3a (submodule push, lives
  in wp-submodule-tests) and 5.3b (parent gitlink update, lives in
  wp-integration); added 5.3-alt fallback for missing-credential case.
- **Cross-package dep hidden** (I4): wp-docs-ci split into wp-docs
  (parallel) and wp-ci-cleanup (depends on wp-public-tests).
- **Pytester registration missing** (I6): task 2.11 switched to
  subprocess-based testing, sidestepping the plugin-registration issue.
- **Graphiti env-key coverage gap** (I7): task 3.1 now enumerates three
  specific env-reference checks.
- **Submodule push atomicity** (A8): added `scripts/push-with-submodule.sh`
  as the documented atomic wrapper.
- **Standalone-mode silent skip** (A6): now requires explicit
  `ALLOW_STANDALONE_SUBMODULE_SKIP=1` opt-in; defaults to pytest.fail.
- **CI workflow hygiene regression risk** (A7): added task 4.4
  (`tests/test_ci_workflow_hygiene.py`) as a guard against future
  workflows re-introducing the populate-dependency.
- **wp-integration write_allow too broad** (I8): tightened to
  `openspec/changes/**` and `.gitmodules`; deny-listed submodule contents.
- **Approach 2 rejection rationale** (F6): rewritten with stronger
  reasons (marker decay, harness coupling, persistent CI burden).

### Decisions

- Accepted the complexity cost of the Layer-2 runtime guard (monkey-
  patching `builtins.open`) because the Copilot-friendly bypass in A2 is
  a realistic threat, not an adversarial one.
- Accepted the submodule's `[tool.uv]` workspace-boundary requirement as
  a one-time setup cost for an otherwise-unprovable isolation claim.
- Accepted the task count growth (from 22 to 27) as a trade-off for TDD
  ordering clarity and explicit scope coverage.
- Reaffirmed NG5 (no content-string deny-list) — the public repo cannot
  enumerate private content, and trying to is a category error.

### Alternatives Considered (Round 1)

- Keeping the substring-only guard and documenting bypasses as known
  limitations — rejected because the documented bypass (A2) is a
  Copilot-default idiom, not an adversarial edge case.
- Keeping the content-string deny-list with a parity test between fixture
  and real submodule — rejected because that parity test would itself be
  the private-content coupling we're trying to eliminate.
- AST-level scanning instead of runtime filesystem patching — deferred;
  the runtime FS guard is strictly more powerful (catches any I/O path,
  not just textual patterns) and simpler to implement.

### Open Questions

- [ ] Does the `builtins.open` patch interact badly with any
  pytest-asyncio fixture initialization order? Task 2.13 will surface
  this during implementation; if issues appear, fallback is to patch
  only `pathlib.*` and accept the `open()` bypass as Layer-1-only.
- [ ] `scripts/push-with-submodule.sh` — does the implementer create it
  from scratch, or is there an existing pattern in `.claude/skills/` to
  reuse? Task 5.3a/5.3b should invoke it, wherever it ends up living.

### Trade-offs

- Accepted a larger plan (5 files grew by ~900 insertions) because Round
  1 surfaced real correctness gaps, not speculative polish.
- Accepted two new scripts (`verify-public-tests-standalone.sh`,
  `verify-submodule-standalone.sh`, `push-with-submodule.sh`) over
  inlining the verification logic into tasks — the scripts are
  reusable, trap-guarded, and keep tasks.md readable.

### Context

Round 1 review used parallel subagent dispatch (three independent
reviewers with distinct mandates) rather than true cross-vendor
convergence, because `agents.yaml` is not scaffolded in this repo (P7
territory). The convergence pattern (independent perspectives, synthesis,
inline fix) was preserved even without vendor diversity.

---

## Phase: Plan Review Round 2 (2026-04-13)

**Agent**: claude-opus-4-6 (2 parallel reviewer subagents) | **Session**: N/A

### Summary

Two reviewers — a convergence verifier (checking Round 1 fix adequacy)
and a fresh adversarial pass (attacking the revised design) — produced
10 findings. The verifier confirmed all 20 Round 1 BLOCKING+MAJOR
findings RESOLVED or SUPERSEDED. The adversarial pass raised 1 BLOCKING
+ 5 MAJOR new findings, and the verifier raised 2 MAJOR clarifications.
All 10 were mechanical cleanups on the fundamentally correct Round-1
design; no design-level re-architecture needed.

### New findings resolved in Round 3 fix

- **B-N1 (BLOCKING) — subprocess bypass**: Layer 2 in-process patches
  miss `subprocess.run(['cat', forbidden_path])`. **Fix**: extended
  Layer 2 to patch `subprocess.Popen.__init__` (scans argv elements).
- **B-N2 (MAJOR) — low-level I/O gap**: `os.open`, `io.FileIO`,
  `codecs.open` bypass the patches. **Fix**: patch `os.open` as the
  canonical syscall choke point (covers all the higher-level wrappers).
- **B-N3 (MAJOR) — push script orphaned**: no task authored
  `scripts/push-with-submodule.sh` though it was referenced by 5.3a/5.3b.
  **Fix**: added task 5.0 with an explicit exit-code contract (exit 47
  for partial-failure).
- **B-N4 (MAJOR) — hygiene test self-trips**: `tests/test_ci_workflow_hygiene.py`
  must contain `personas/personal/` as part of its grep pattern; Layer 1
  would reject it. **Fix**: files use dynamic needle construction from
  `FORBIDDEN_PATH_NAMES`; also added to Layer 1 exclusion list
  (defence-in-depth).
- **B-N5 (MAJOR) — PyPI package collision**: `assistant` exists as an
  unrelated PyPI package; positive-import assertion could fail
  spuriously. **Fix**: assertion now imports `assistant.core.persona`
  (qualified path, won't collide).
- **B-N6 (MAJOR) — parent workspace forward-compat**: if parent
  pyproject later adds `[tool.uv.workspace] members = ['personas/*']`,
  the submodule's own `workspace.members = []` cannot veto inclusion.
  **Fix**: added `tests/test_workspace_hygiene.py` to assert the parent
  does NOT declare `personas/*` as a workspace member.
- **B-N7 (MINOR) — pytest rootdir ambiguity**: the fresh-venv proof
  script ran pytest from parent repo root; parent's plugins could load.
  **Fix**: script now `cd`s to `personas/personal/` before invoking
  pytest with `--rootdir=.` and `--override-ini='addopts='`.
- **B-N8 (MINOR) — plugin install silent failure**: if a future CPython
  refuses Python-level rebinding of `Path.open`, the patches silently
  fail to install and Layer 2 is disabled. **Fix**: added plugin
  self-probe at `pytest_configure` that fails the session if the canary
  does not raise.
- **A-N1 (MAJOR) — task 5.4 self-contradiction**: task said "subsumed
  by 5.3b" but was listed as a required task. **Fix**: 5.3b pushes the
  parent branch; 5.4 opens the PR via `gh pr create`. Unambiguous.
- **A-N2 (MAJOR) — 5.3-alt trigger ambiguity**: unclear whether
  dispatch-time or runtime triggered. **Fix**: documented as an explicit
  dual contract — dispatch-time quarantine driven by
  `requires_private_repo_write` constraint, PLUS runtime exit-code-47
  fallback if 5.3a fails after dispatch.

### Task/package structure changes

- Added task 5.0 (push-script authoring), task 4.4 renamed from
  generic workflow-hygiene to hygiene test with dynamic-needle
  construction, task 4.5 added for parent-workspace hygiene. Tasks 4.4
  and 4.5 moved from wp-public-tests to wp-ci-cleanup so their RUN
  happens after 4.1 (populate-step removal). wp-ci-cleanup now also
  writes `tests/test_ci_workflow_hygiene.py` and
  `tests/test_workspace_hygiene.py` (expanded write_allow; deny list
  adjusted to exclude the specific named files from the tests/ deny).

### Convergence verdict

All Round 1 findings RESOLVED or SUPERSEDED; all Round 2 findings
addressed inline. The plan is coherent and ready for implementation.
Round 3 was fix-only (no new review pass) because the Round 2 findings
were mechanical and each had a clear, targeted fix; a third round
would be diminishing returns. Explicit documentation of remaining
out-of-coverage surface (mmap, ctypes, os.system on Windows,
deliberately-split subprocess argv) is captured in design R2.

### Trade-offs

- Accepted the Layer-2 patch surface growth (now 6 entry points
  including subprocess) as the honest price of closing B-N1's bypass
  class. The plugin is larger but still under ~200 lines.
- Accepted the `wp-ci-cleanup` package's expanded scope to own the two
  hygiene tests rather than splitting them into a new package. Cleaner
  dispatcher DAG vs. stricter single-responsibility.

### Open Questions

- [ ] Does patching `subprocess.Popen.__init__` interfere with
  pytest-xdist worker spawning? Worth surfacing during IMPLEMENT if
  issues appear; fallback is to scope the subprocess patch to test
  invocations only (not pytest-internal subprocess).
- [ ] Does `os.open` patching interfere with pytest's own file-based
  fixtures (tmp_path, capsys captures)? Theoretically no (those
  paths don't match `personas/<name>/`), but verify during 2.13
  implementation.
