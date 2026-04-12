# Tasks: bootstrap-vertical-slice

Tasks are ordered TDD-style within each phase: test tasks first, implementation
tasks depend on their corresponding tests. Phases are ordered to produce a
compileable/importable tree at the end of each phase. Each test task lists the
exact scenario names it must encode (not just counts).

## Phase 1 — Shared fixtures & role definitions (no Python code yet)

- [ ] 1.1 Create `roles/_template/role.yaml` and `roles/_template/prompt.md`
  matching the v4.1 spec template.
- [ ] 1.2 Create `roles/researcher/` with `role.yaml`, `prompt.md`, and
  `skills/deep_research.md`.
- [ ] 1.3 Create `roles/planner/` with `role.yaml`, `prompt.md`, and
  `skills/strategic_planning.md`.
- [ ] 1.4 Create `roles/chief_of_staff/` with `role.yaml`, `prompt.md`, and
  `skills/{briefing.md,delegation.md,triage.md}`.
- [ ] 1.5 Create `roles/writer/` with `role.yaml`, `prompt.md`, and
  `skills/content_drafting.md`.
- [ ] 1.6 Create `roles/coder/` with `role.yaml`, `prompt.md`, and
  `skills/code_analysis.md`.
- [ ] 1.7 Create `personas/_template/` with `persona.yaml`, `prompt.md`,
  `memory.md`, and placeholder `roles/.gitkeep` + `extensions/.gitkeep`.
  Do NOT create `tools.yaml` — its schema is owned by P2 (http-tools-layer)
  and will be added then.
- [ ] 1.8 Populate `personas/personal/` submodule with `persona.yaml`,
  `prompt.md`, `memory.md`, and `roles/{researcher,chief_of_staff}.yaml`
  override files. (No `tools.yaml` — see 1.7.)
- [ ] 1.9 Scaffold `__init__.py` in every new Python package directory:
  `src/assistant/`, `src/assistant/core/`, `src/assistant/harnesses/`,
  `src/assistant/extensions/`, `src/assistant/delegation/`, `tests/`.
- [ ] 1.10 Commit the submodule changes from 1.8 inside `personas/personal/`
  and push to the private origin (`agentic-assistant-config-personal`);
  the outer repo's submodule-SHA bump will be committed later (task 6.6).

## Phase 2 — Core library: persona, role, composition (TDD)

- [ ] 2.1 Write `tests/test_persona_registry.py` encoding the following
  scenarios from `specs/persona-registry/spec.md`:
  - Populated submodule is discovered
  - Template directory is excluded
  - Uninitialized submodule is skipped
  - Load resolves env var references
  - Missing env var resolves to empty string, not error
  - Loaded result is cached
  - prompt.md is loaded
  - memory.md is optional
  - Error message lists alternatives
  - Private extension takes precedence
  - Public fallback used when no private override
  - Missing module logs warning and continues
  **Spec scenarios**: all 12 scenarios across 5 requirements.
  **Dependencies**: 1.7, 1.8, 1.9
- [ ] 2.2 Implement `src/assistant/core/persona.py` with `PersonaConfig`
  dataclass, `PersonaRegistry.discover/load/load_extensions`, and `_env`.
  **Dependencies**: 2.1
- [ ] 2.3 Write `tests/test_role_registry.py` encoding the following scenarios
  from `specs/role-registry/spec.md`:
  - Public role is discovered
  - Template directory is excluded
  - Disabled role is filtered out
  - Base role loads without overrides
  - prompt_append extends the base prompt
  - additional_preferred_tools extends the list
  - delegation_overrides update individual keys
  - context_overrides update individual keys
  - Missing role raises with available list
  **Spec scenarios**: all 9 scenarios across 3 requirements.
  **Dependencies**: 1.1–1.6, 1.8, 2.2
- [ ] 2.4 Implement `src/assistant/core/role.py` with `RoleConfig` dataclass
  and `RoleRegistry.discover/available_for_persona/load`. Merge must handle
  `prompt_append`, `additional_preferred_tools`, `delegation_overrides`, and
  `context_overrides` (D4 in design.md).
  **Dependencies**: 2.3
- [ ] 2.5 Write `tests/test_composition.py` encoding the following scenarios
  from `specs/prompt-composition/spec.md`:
  - All three layers are present in order
  - Empty persona augmentation is omitted
  - Empty role prompt is omitted
  - Active configuration lists persona, role, and sub-roles
  - No allowed sub-roles renders "none"
  - always_plan roles include a planning line
  **Spec scenarios**: all 6 scenarios across 2 requirements.
  **Dependencies**: 2.4
- [ ] 2.6 Implement `src/assistant/core/composition.py` with
  `BASE_SYSTEM_PROMPT`, `compose_system_prompt`, and `_build_active_context`.
  **Dependencies**: 2.5

## Phase 3 — Harnesses & extensions (TDD)

- [ ] 3.1 Write `tests/test_extensions.py` encoding the following scenarios
  from `specs/extension-registry/spec.md`, for each of the 7 stub modules
  (`ms_graph`, `teams`, `sharepoint`, `outlook`, `gmail`, `gcal`, `gdrive`):
  - Stub implementation satisfies Protocol
  - Each stub exports create_extension
  - Stubs return empty tool lists
  - Stub health_check returns True
  - Scopes are stored on the instance
  - Missing scopes default to empty list
  **Spec scenarios**: all 6 scenarios across 3 requirements.
  **Dependencies**: 2.2
- [ ] 3.2 Implement `src/assistant/extensions/base.py` (`Extension` Protocol,
  `@runtime_checkable`) and the 7 stubs
  `{ms_graph,teams,sharepoint,outlook,gmail,gcal,gdrive}.py`, each exposing
  `create_extension(config: dict)`.
  **Dependencies**: 3.1
- [ ] 3.3 Write `tests/test_harnesses.py` encoding the following scenarios
  from `specs/harness-adapter/spec.md`:
  - Instantiating the abstract class raises
  - Concrete subclass must implement all methods
  - Harness name is deep_agents
  - create_agent uses the persona-configured model
  - create_agent includes extension tools
  - invoke returns the last assistant message content
  - Factory returns MS AF harness for enabled persona
  - MS AF create_agent raises NotImplementedError
  - Unknown harness name raises
  - Disabled harness raises
  **Spec scenarios**: all 10 scenarios across 4 requirements.
  **Dependencies**: 2.2, 2.6, 3.2
- [ ] 3.4 Implement
  `src/assistant/harnesses/{base.py,deep_agents.py,ms_agent_fw.py,factory.py}`.
  `MSAgentFrameworkHarness.create_agent` raises `NotImplementedError` with a
  message referencing P5 (D2 in design.md).
  **Dependencies**: 3.3

## Phase 4 — Delegation (TDD)

- [ ] 4.1 Write `tests/test_delegation.py` using a `FakeHarness` that captures
  `spawn_sub_agent` calls, encoding the following scenarios from
  `specs/delegation-spawner/spec.md`:
  - Disallowed sub-role raises ValueError
  - Allowed sub-role proceeds to harness
  - Exceeding max_concurrent raises
  - Count is decremented after delegation completes
  - Disabled role for persona raises
  **Spec scenarios**: all 5 scenarios across 3 requirements.
  **Dependencies**: 2.4, 3.4
- [ ] 4.2 Implement `src/assistant/delegation/spawner.py`. Use a manual
  integer counter (not `asyncio.Semaphore`) so enforcement is synchronous at
  `delegate()` entry — the FakeHarness in 4.1 can hold the counter busy by
  awaiting a set event. (Skip `router.py` — deferred to P8.)
  **Dependencies**: 4.1

## Phase 5 — CLI (TDD)

- [ ] 5.1 Write `tests/test_cli.py` using `click.testing.CliRunner` and a
  `StubHarness` injected via a CLI-level seam (e.g., a module-level
  `_create_harness` hook), encoding the following scenarios from
  `specs/cli-interface/spec.md`:
  - Entry point is installed
  - Only initialized personas are listed
  - Listing roles without persona errors
  - Listing roles for personal persona
  - Default role used when -r omitted
  - Unknown persona fails with hint
  - Default harness is deep_agents
  - -h ms_agent_framework surfaces the stub error
  - REPL echoes harness response
  - /role switches the active role mid-session
  - /role with unknown role prints error, keeps current role
  - Valid delegation returns sub-agent output
  - Invalid /delegate usage prints usage hint
  **Spec scenarios**: all 13 scenarios across 7 requirements.
  **Dependencies**: 2.2, 2.4, 3.4, 4.2
- [ ] 5.2 Implement `src/assistant/cli.py` with Click entry point,
  `--list-personas`, `--list-roles`, `-p`, `-r`, `-h`, REPL, `/role`,
  `/delegate`. Defer HTTP tool discovery (P2) — the CLI logs a warning and
  passes an empty tool list. Expose a `_create_harness` seam for tests.
  **Dependencies**: 5.1

## Phase 6 — Supporting assets

- [ ] 6.1 Create `scripts/setup-persona.sh` and `scripts/init-persona-repo.sh`,
  make them executable (`chmod +x`).
- [ ] 6.2 Create `CLAUDE.md`, `AGENTS.md`, and update `README.md` with setup
  instructions.
- [ ] 6.3 Create `.env.example` with all env vars referenced by personas.
- [ ] 6.4 Create `.github/workflows/ci.yml` running `ruff check`, `mypy`
  (permissive: `strict = false`, `check_untyped_defs = true`), `pytest` on
  Python 3.12 / `ubuntu-latest`.
- [ ] 6.5 Update root `.gitignore` to include `__pycache__/`, `*.pyc`,
  `.venv/`, `dist/`, `*.egg-info/`, `.env`, `personas/*.env`, `.vscode/`,
  `.idea/`, `.DS_Store`, `.status-cache.json`.
- [ ] 6.6 Stage and commit the outer repo (includes the bumped
  `personas/personal` submodule SHA from 1.10). Push feature branch to
  `origin`.

## Phase 7 — Validation

- [ ] 7.1 Run `uv run ruff check .` — zero errors.
- [ ] 7.2 Run `uv run mypy src tests` — zero errors under permissive config.
- [ ] 7.3 Run `uv run pytest` — all tests pass.
- [ ] 7.4 Smoke: `uv run assistant --list-personas` prints only `personal`.
- [ ] 7.5 Smoke: `uv run assistant -p personal --list-roles` prints all 5
  public roles.
- [ ] 7.6 `openspec validate bootstrap-vertical-slice --strict` passes.
