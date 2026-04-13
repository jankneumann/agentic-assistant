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
