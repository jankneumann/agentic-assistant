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
