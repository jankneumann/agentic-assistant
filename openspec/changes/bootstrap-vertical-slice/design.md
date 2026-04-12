# Design: bootstrap-vertical-slice

## Context

This is the first change in the repo. The overarching architecture is fixed by
`agentic-assistant-bootstrap-v4.1.md`; the design choices recorded here are the
ones specific to landing a working vertical slice in a single change.

## Architectural Seams Exercised

Each of the seven capabilities corresponds to a seam that later proposals will
extend. The vertical slice's job is to prove each seam's **contract**, not its
full behavior.

| Seam | Interface exercised | Later proposal |
|------|---------------------|----------------|
| persona-registry | `PersonaRegistry.load(name) → PersonaConfig` | P3 (DB), P6 (work) |
| role-registry | `RoleRegistry.load(name, persona) → RoleConfig` | — (stable) |
| prompt-composition | `compose_system_prompt(persona, role) → str` | — (stable) |
| harness-adapter | `HarnessAdapter.create_agent / invoke / spawn_sub_agent` | P5 (MS AF) |
| extension-registry | `Extension` Protocol + `as_langchain_tools() / as_ms_agent_tools()` | P4, P5 |
| delegation-spawner | `DelegationSpawner.delegate(role, task)` | P8 (parallel) |
| cli-interface | Command flags + REPL commands | P7 (harness CLIs) |

## Key Decisions

### D1: Extension stubs return empty tool lists, not `NotImplementedError`

**Why**: the CLI must be able to boot with `extensions: []` in
`persona.yaml` *and* with extensions configured but unimplemented. Raising
`NotImplementedError` would force every test to mock the extension loader.
Empty lists let the harness compose without special-casing.

**Trade-off**: a persona config that references a stub extension silently does
nothing at tool-call time. The CLI logs
`Extensions loaded: N (gmail, gcal, ...)` on startup so the user knows which
are actually wired; P4/P5 replaces stubs with real implementations.

### D2: MS Agent Framework harness is registered but raises on create

**Why**: keeping the harness in the factory registry means the CLI's
`-h ms_agent_framework` flag works and gives a clear error, rather than
"unknown harness". This exercises the harness-factory seam without requiring
the `agent-framework-*` packages to actually work (they're optional extras).

**Trade-off**: a user who enables MS AF in their persona and passes
`-h ms_agent_framework` will hit a runtime error. Acceptable for the slice
because only the personal persona is populated (where MS AF is disabled in
config), so the error is only reachable by explicit override.

### D3: `personas/_template/` is tracked in the public repo

**Why**: the setup script that creates a new private persona repo copies from
this template. If it lived only in a private repo, bootstrapping a new persona
would require cloning a private repo first — creating a chicken-and-egg for
new users.

**Trade-off**: the template contains `persona.yaml` skeletons with env-var
placeholders; these are safe because no real secrets are embedded.

### D4: Role override merge is **shallow field-level**, not deep

**Why**: override semantics are explicit per field
(`prompt_append` appends, `additional_preferred_tools` extends,
`delegation_overrides` / `context_overrides` update dict-wise). Deep merging
would confuse authors ("does an override's empty list replace or extend?").

**Trade-off**: if later proposals introduce new role fields, the merger needs
explicit cases for them. Documented in `RoleRegistry.load` docstring.

### D5: Typed dataclasses, not Pydantic models, for `PersonaConfig` / `RoleConfig`

**Why**: these are internal aggregates, not external boundary types. YAML
parsing does the validation (via `yaml.safe_load` + KeyError on missing keys).
Pydantic would add a validation layer redundant with YAML schema validation.

**Trade-off**: no per-field validators. If a later proposal needs coerced or
validated fields (e.g., URL types), revisit then.

### D6: Environment variables resolved at `load()` time, cached per-persona

**Why**: `_env()` returns `""` for missing vars (not raising), so startup
doesn't fail on an incomplete `.env`. The CLI surfaces the empty string later
("No database URL for persona 'X'. Set WORK_DATABASE_URL.") at use time.

**Trade-off**: mistyped env var names won't fail fast. Mitigated by the
`.env.example` file listing all expected vars.

### D7: `deepagents` + `langchain-anthropic` only; no `agent-framework-*` in base deps

**Why**: `agent-framework-*` pulls in heavy MS-specific dependencies (Azure SDK,
etc.). Installed only via the `[project.optional-dependencies.ms]` extra.
P5 will make this extra required when MS Graph extensions land.

**Trade-off**: `pip install assistant` doesn't get MS AF by default.
Documented in README.

### D8: No worktree-based implementation

**Why**: the `autopilot` skill often uses worktrees to parallelize. For this
bootstrap there's no existing code to conflict with and the feature branch
itself is effectively a clean slate. Using a worktree would add overhead with
zero isolation benefit.

**Trade-off**: parallel vendor implementation (if used for IMPL_REVIEW) must
scope packages by file paths on the same branch. Write-scope collisions avoided
by decomposing into disjoint directory trees (see `work-packages.yaml`).

## Testing Strategy

- **Unit**: every capability has a dedicated test module. All tests use the
  real `personas/_template/` and in-repo `roles/` directories — no mocking of
  the filesystem. This makes tests also validate that template configs parse.
- **Smoke**: `tests/test_cli.py` invokes `--list-personas` and `--list-roles`
  against a populated `personas/personal/` fixture via `click.testing.CliRunner`.
- **No integration with real LLMs in this slice**: `test_deep_agents_harness.py`
  asserts on agent construction only (no `.ainvoke`) — an LLM-exercising test
  suite arrives in P3/P4 once there's something meaningful to test.
- **CI** runs `ruff check`, `mypy`, `pytest` on Python 3.12 against Ubuntu.

## Deferred Until Later Proposals

- **HTTP tool wiring** (`cli.py` currently accepts but doesn't use
  `tool_sources` — logs a warning and passes empty tool list to the harness).
- **DB initialization** (the harness receives no DB-backed memory in this slice;
  only filesystem memory via `memory_files`).
- **Extension health checks as a CLI command** (protocol includes
  `health_check()` but no CLI command yet).

## Open Questions

None blocking. Interface choices for deferred proposals will be confirmed when
those proposals plan.

### D9: CLI short flag for `--harness` is `-H`, not `-h`

**Why**: Click reserves `-h` for `--help`. Overriding `help_option_names` to
free up `-h` would break muscle memory for every user coming from other
Click-based CLIs. The spec uses `-H` (uppercase) as the documented short
form for `--harness`.

**Trade-off**: minor deviation from the informal `-h` in the original v4.1
spec document. Updated spec + proposal + README reflect the `-H` choice.

## Deferred Schemas (explicitly not owned by P1)

- **`tools.yaml`**: the v4.1 spec's persona template includes this file, but
  its schema (which HTTP tool sources, auth headers, allowed-tool whitelists)
  belongs to P2 (`http-tools-layer`). P1 does not create `tools.yaml` in
  `personas/_template/` or `personas/personal/` — P2 will add it, define its
  schema in that proposal's specs, and wire the CLI's `-p` flow to read it.
  P1's `cli.py` passes an empty tool list to the harness and logs a warning.
