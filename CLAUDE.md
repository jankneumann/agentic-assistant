# agentic-assistant

Personal AI assistant with plugin-based persona system and composable roles.

## Repo Structure

- **Public repo**: code, roles, extension implementations, CLI
- **Private config repos**: mounted as git submodules under `personas/`
- Each persona (work, personal) is its own private repo

## Key Concepts

- **Persona** = execution boundary (DB, auth, tools) — private config
- **Role** = behavioral pattern (prompt, workflow, delegation) — public base
- Persona × Role compose via a three-layer prompt system
- Sub-agents inherit persona, switch role

## Setup

```bash
git clone https://github.com/jankneumann/agentic-assistant.git
cd agentic-assistant

# Initialize persona submodules you need (each requires its private repo access)
git submodule update --init personas/personal
# git submodule update --init personas/work   # requires Comcast GH Enterprise

uv sync
uv run assistant -p personal
```

## Directory Layout

- `roles/` — shared role definitions (public, reusable)
- `personas/` — submodule mount points for private config repos
- `personas/_template/` — template for creating new personas (public)
- `src/assistant/core/` — harness-agnostic library (persona, role, composition)
- `src/assistant/harnesses/` — harness adapters (Deep Agents implemented;
  MS Agent Framework is a registered-but-stubbed placeholder until the
  `ms-graph-extension` phase)
- `src/assistant/extensions/` — extension implementations (P1 ships empty-tool
  stubs for `ms_graph`, `teams`, `sharepoint`, `outlook`, `gmail`, `gcal`,
  `gdrive`; real impls land in `ms-graph-extension` and `google-extensions`
  phases)
- `src/assistant/delegation/` — sub-agent spawning
- `src/assistant/cli.py` — `assistant` CLI entry point

## Adding a New Persona

1. Scaffold a new private repo from template:
   `./scripts/init-persona-repo.sh /tmp/my-config`
2. Push it to a private Git host
3. Mount it: `./scripts/setup-persona.sh myname https://git.example.com/my-config`

## Adding a New Role

1. `cp -r roles/_template roles/newrole`
2. Edit `roles/newrole/role.yaml` and `prompt.md`
3. Optional: add persona-specific overrides in private repos at
   `personas/<persona>/roles/newrole.yaml`

## OpenSpec Workflow

This repo uses [OpenSpec](https://github.com/Fission-AI/OpenSpec) for
spec-driven development. See `openspec/roadmap.md` for the full phase
sequence and dependency graph. Each proposal lives in
`openspec/changes/<change-id>/`.

Common commands:
- `openspec list` — in-progress changes
- `openspec list --specs` — current specs
- `openspec validate <change-id> --strict`
- `openspec show <change-id>`

## Conventions

- Python 3.12, type hints, Ruff, pytest
- Extension code in public repo, activation config in private repos
- Each persona gets its own database (ParadeDB Postgres) — wired in
  the `memory-architecture` phase
- Tests run against the in-repo `tests/fixtures/personas/` (public tests)
  or the persona's own submodule (persona-specific tests), never against
  the real `personas/<name>/` submodule from public code; see
  `tests/conftest.py`.
- Public tests use fixtures only (`tests/fixtures/personas/`);
  persona-specific tests live in each persona's private submodule and
  must be self-contained (no imports from `src/assistant/*`); the
  two-layer privacy guard in `tests/conftest.py` +
  `tests/_privacy_guard_plugin.py` enforces this at collection time
  (substring scan) and at runtime (FS I/O patching).

## Known gotchas

See `docs/gotchas.md` for traps we've hit and how to avoid them
(workflow-YAML `on:` boolean coercion, submodule+CI interaction, `uv_build`
`__init__.py` requirement, `mock.patch` vs lazy imports, OpenSpec SHALL
placement). Read this before adding new proposals, CI steps, or spec
deltas.

## What's Not Yet Wired

See `openspec/roadmap.md` for the full sequence. Notable gaps:

- **`http-tools-layer` phase — HTTP tools**: `cli.py` does not yet call
  `discover_tools`; it passes an empty tool list and logs a warning.
- **`memory-architecture` phase — memory layer**: no per-persona Postgres
  or Graphiti yet.
- **`ms-graph-extension` / `google-extensions` phases**: all stubs return
  `[]` from
  `as_langchain_tools()`.
- **`work-persona-config` phase**: submodule + role overrides come
  when the work machine is available.
