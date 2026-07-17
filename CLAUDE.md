# agentic-assistant

Personal AI assistant with plugin-based persona system and composable roles.

**Always use Context7 MCP** for library/API documentation, setup steps, or
code generation involving external libraries — your training data may not
reflect recent changes.

## Documentation Index

| Doc | Purpose |
|-----|---------|
| [Gotchas](docs/gotchas.md) | Subtle traps hit during development — read before touching CI, submodules, OpenSpec, or tests |
| [Bootstrap v4.1](docs/agentic-assistant-bootstrap-v4.1.md) | Origin brief and architectural rationale |
| [Perplexity Feedback](docs/perplexity-feedback.md) | External design review notes |
| [Prompts](docs/prompts/) | Briefings used to seed sub-agents and planning runs |
| [OpenSpec Roadmap](openspec/roadmap.md) | Phase sequence and dependency graph for in-progress work |

## Repo Structure

- **Public repo**: code, roles, extension implementations, CLI
- **Private config repos**: mounted as git submodules under `personas/`
- Each persona (work, personal) is its own private repo

## Key Concepts

- **Persona** = execution boundary (DB, auth, tools) — private config
- **Role** = behavioral pattern (prompt, workflow, delegation) — public base
- Persona × Role compose via a three-layer prompt system
- Sub-agents inherit persona, switch role

## Essential Commands

```bash
# Setup
git submodule update --init personas/personal     # one-time per persona
uv sync                                            # install deps

# Run
uv run assistant -p personal                       # CLI with persona
uv run assistant serve -p personal -r coder        # AG-UI SSE server (loopback only)
# Smoke test from another shell:
#   curl -N -H 'Content-Type: application/json' \
#     -d '{"message":"hello"}' http://127.0.0.1:8765/chat
#   curl http://127.0.0.1:8765/health

# Test (public suite — uses fixtures, never real submodule)
uv run pytest tests/
scripts/verify-public-tests-standalone.sh          # verifies privacy boundary

# Scheduler daemon (P7)
uv run assistant daemon -p personal               # run schedules: jobs until Ctrl-C
uv run assistant daemon -p personal --serve       # + AG-UI SSE server in-process

# Simulation + eval loop (P27)
uv run assistant simulate                          # fixture-backed tool simulator (127.0.0.1:8901);
                                                   # prints the SIM_*_URL / ASSISTANT_PERSONAS_DIR exports
evaluation/run-gate.sh                             # eval gate: gen-eval suites vs the sim persona
                                                   # (SKIPs cleanly without the tools-repo checkout)

# OpenSpec workflow
openspec list                                      # in-progress changes
openspec list --specs                              # current specs
openspec validate <change-id> --strict
openspec show <change-id>
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
  phases). Since P10 `extension-lifecycle`, extensions may implement
  optional async hooks `initialize()` / `shutdown()` /
  `refresh_credentials()` — NOT required Protocol members (private
  structural extensions stay compatible); subclass `ExtensionBase`
  for no-op defaults. `PersonaRegistry.load_extensions()` (sync; or
  `load_extensions_async()` inside an event loop) runs `initialize()`
  post-load (a failure disables just that extension) and registers
  shutdown handling (`shutdown_extensions()` + atexit)
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

## Scheduler & Daemon Mode (P7)

`core/scheduler.py` runs a persona's `schedules:` jobs (see
`personas/_template/persona.yaml` for the annotated schema):

- **Triggers**: `cron:` (5-field croniter, UTC), `interval:` (seconds,
  first fire one period after start), `calendar:` (+ `lead_minutes`,
  default 15 — fires ahead of upcoming events from a
  `CalendarTriggerSource` extension; the protocol ships now, real
  gcal/outlook sources land in later phases, so declared calendar
  jobs are skipped with a warning until then). Missed fires are
  skipped, never replayed.
- **Execution**: each run spawns a fresh SDK harness (`create_harness`
  → `create_agent` → `invoke`) with the job's `role`; results persist
  through the harness's P21 post-turn memory capture. Per-job error
  isolation — a failing job never kills the daemon.
- **Model routing**: jobs resolve their chat model under the job's
  `consumer` binding (default `scheduler`) via a consumer-rewriting
  ModelProvider wrapper — bind `scheduler:` to a cheap/local entry in
  `models:` so background work stays off the interactive tier (P19).
- **CLI**: `assistant daemon -p <persona>` (options: `-H`, `--serve`
  + `--host/--port` to co-host the AG-UI server). Validates jobs,
  roles, and harness up front; SIGINT/SIGTERM shut down gracefully
  (scheduler stop → extension `shutdown()` hooks).
- **Daemons + budgets**: set
  `guardrails.budgets.model_call.persist: file` — the default
  in-memory spend ledger resets on every restart (the daemon warns
  about this at startup).

## Simulation & Eval Loop (P27)

The eval feedback loop lives in two places:

- `src/assistant/simulation/` — fixture-backed simulator
  (`assistant simulate`) serving per-source `/openapi.json` mock tool
  endpoints from `routes.yaml` manifests, consumed by the EXISTING
  http_tools discovery (simulation = persona config + env vars, zero
  new agent code paths); plus the offline interaction→scenario-stub
  export behind `assistant export-eval-dataset`.
- `evaluation/simulation/` — the public **sim persona**
  (`ASSISTANT_PERSONAS_DIR=evaluation/simulation/personas`), the seed
  corpus (`sources/`, operation ids in lockstep with
  `roles/*/role.yaml` preferred_tools — a public test enforces this),
  and the gen-eval scenario suites (`scenarios/`).

`evaluation/run-gate.sh` is the eval gate consumed by P28 and by
prompt/routing config changes: it shells out to the external gen-eval
project (ADR 0006 — never a dependency), exits nonzero on scenario
failure, and SKIPs with exit 0 when the `agentic-coding-tools`
checkout is absent (`EVAL_GATE_REQUIRE=1` makes that fatal). Exported
dataset stubs land git-ignored in `evaluation/datasets/exported/` and
need human completion before promotion into a suite — self-improvement
is propose → eval → human-approved diff, never self-merge.

## OpenSpec Workflow

Spec-driven development via [OpenSpec](https://github.com/Fission-AI/OpenSpec).
See `openspec/roadmap.md` for phase sequence. Each proposal lives in
`openspec/changes/<change-id>/`. Common commands are listed under
**Essential Commands** above.

## Skills

This repo **consumes** skills from the canonical source at
`~/Coding/agentic-coding-tools/skills/`. The installed copies under
`.agents/skills/` and `.claude/skills/` are generated by
`skills/install.sh` over there and are **overwritten on next sync**.

- **NEVER edit** `.agents/skills/` or `.claude/skills/` in this repo directly.
  Edit in `agentic-coding-tools/skills/`, then re-run the installer.
- See `agentic-coding-tools/CLAUDE.md` for the full skill workflow
  (tiered execution, worktree discipline, parallel review).

## Git Conventions

- **Branch naming**: `openspec/<change-id>` for OpenSpec-driven features
- **Commit format**: `feat(scope):`, `fix(scope):`, `test(scope):`,
  `docs(scope):`, `chore(scope):` — reference the OpenSpec change-id
- **Commit quality**: one logical commit per task, no WIP fragments
- **Submodule pushes**: use `scripts/push-with-submodule.sh` when a
  change touches both the public repo and a persona submodule — it
  orders the pushes so the parent never references an unreachable
  submodule SHA

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

## Critical Gotchas

Full prose in [docs/gotchas.md](docs/gotchas.md). These are the ones
that waste the most time:

| # | Issue | Solution |
|---|-------|----------|
| G1 | GH Actions silently ignores workflows with unquoted `on:` key (YAML 1.1 boolean coercion) | Always write `"on":` with quotes |
| G2 | Tests fail on CI when private submodule is absent | Mirror submodule under `tests/fixtures/personas/<name>/` and populate in CI before pytest |
| G3 | `uv_build` rejects packages without `__init__.py` | Never delete the scaffolded `src/<pkg>/__init__.py` — edit it |
| G4 | `mock.patch()` can't find lazily-imported attributes | Move import to module top-level, or patch at source module |
| G5 | OpenSpec `--strict` wants SHALL/MUST in opening clause of Requirement body | Lead with `The system SHALL …`, move "when" qualifiers after |
| G6 | Private-persona content leaking into public tests | Use `FIXTURE_PERSONA_SENTINEL_v1` assertions; never hard-code `personas/personal/` strings; trust the two-layer guard |
| G7 | Submodule standalone tests silent-skip when parent `roles/` is absent | Default is strict fail; opt in with `ALLOW_STANDALONE_SUBMODULE_SKIP=1` when running the submodule in isolation |
| G8 | Local `mypy src/` passes but CI `mypy src tests` fails on test-side narrowing errors | Always run the full CI scope locally (`uv run mypy src tests`) before pushing — see Landing the Plane quality gates |

## What's Not Yet Wired

See `openspec/roadmap.md` for the full sequence. Notable gaps:

- **`google-extensions` phase**: `gmail`, `gcal`, `gdrive` still
  return `[]` from `as_langchain_tools()`. The four MS extensions
  (`ms_graph`, `outlook`, `teams`, `sharepoint`) are real after
  `ms-graph-extension` (P5) — they ship code only and stay disabled
  on the personal persona until the work persona lands in P15.
- **`work-persona-config` phase**: submodule + role overrides come
  when the work machine is available. Until then no persona enables
  the four MS extensions.
- **Model routing is live through the ModelProvider seam** (P19
  `model-provider-routing`, registry-only per owner review verdict
  #3): both SDK harnesses resolve their chat model via
  `CapabilitySet.models` (slot #6) and per-consumer bindings
  (`core/capabilities/model_bindings.py`). The persona `models:`
  registry (`entries:` + consumer `bindings:`; tag-filtered, ordered
  fallback chains, OpenRouter-mirrored catalog metadata) is the ONLY
  model-selection mechanism — the legacy `harnesses.<name>.model`
  strings are gone; personas without a `models:` section resolve
  against a registry synthesized from the built-in harness defaults
  (`default_model_registry`). Every binding is budget-gated via
  `GuardrailProvider.check_action(action_type="model_call")` and API
  keys resolve through the `CredentialProvider` seam. Still deferred:
  OpenRouter catalog **sync** and health-checked local GX10 entries
  (P20), and the MSAF binding covers `openai-compatible` refs only
  (no connector packages for the other dialects).
- **Security hardening is live** (P13 `security-hardening`):
  guardrails are no longer allow-all-only — a persona `guardrails:`
  section (budgets / policies / delegation, see
  `personas/_template/persona.yaml`) selects `PolicyGuardrails`
  through the resolver on both host and sdk branches; personas
  without the section keep `AllowAllGuardrails`. Model-call budgets
  enforce per-persona daily/monthly USD ceilings from P19 cost
  metadata (in-memory ledger by default; `persist: file` writes
  `.cache/guardrails/spend.json`; a persona-DB ledger is deferred).
  `require_confirmation` on `model_call` still DENIES until the
  approval interrupt flow exists (needs durable sessions). Credential
  reads are persona-scoped: a git-ignored persona `.env` loads into a
  scoped namespace (persona values first, process env fallback, no
  `os.environ` pollution) consumed via `PersonaConfig.credentials`
  everywhere (persona load, http_tools auth, model bindings,
  graphiti, MSAL); OpenBao becomes the production backend in P25.
  Private extensions are hash-verified against an optional
  `extensions/manifest.yaml` before execution (`assistant persona
  hash-extensions` generates it; mismatch disables that extension,
  missing manifest warns).
- **Memory retrieval + capture are live but prepend-only** (P21
  `memory-retrieval-activation`): both SDK harnesses (DeepAgents and
  MSAF) consume `MemoryPolicy.get_recent_snippets(persona, role,
  limit=10)` at `create_agent` time and prepend the result under a
  `## Recent context` heading. `PostgresGraphitiMemoryPolicy` returns
  live snippets from `MemoryManager` (facts / preferences /
  interaction summaries + Graphiti semantic search, degrading to
  Postgres-only); `FileMemoryPolicy` returns bounded `memory.md`
  excerpts; `HostProvided` stays `[]` (host owns memory). After a
  successful turn, harnesses store a one-line interaction summary via
  `record_interaction` (error-swallowed — memory never breaks a
  conversation). Still deferred: mid-turn retrieval / structured
  memory items in MSAF (blocked on an `agent-framework` SDK injection
  point — see the `ms-agent-framework-harness` spec "Follow-up scope"
  note), Graphiti episode write-back on capture, and durable session
  persistence (owned by `capability-protocols-v2`).
- **`agent-framework` packaging — RESOLVED (X3 repo-hygiene,
  2026-07-16)**: the repo now pins `agent-framework-core` +
  `agent-framework-openai` (1.10.x) instead of the `agent-framework`
  meta package. The 1.0.x meta line no longer resolves on a fresh
  `uv lock` (its graph reaches a yanked pre-release), and 1.10 core
  ships a real `agent_framework/__init__.py`, eliminating the old
  empty-namespace quirk. One consequence: `agent_framework.azure_openai`
  no longer exists — the MSAF harness's `chat_client: azure_openai`
  branch degrades to its documented install error until an Azure
  OpenAI connector package ships (MSAF follow-up scope). Tests still
  mock with `unittest.mock.patch(..., create=True)` and are
  unaffected.

### Known follow-ups from archived changes

Filed as GitHub issues labeled `followup` + `openspec:<change-id>`;
browse with `gh issue list --label followup`:

- **http-tools-layer** (P3, archived 2026-04-24):
  - #16 — support OpenAPI requestBody with `additionalProperties`
  - #17 — propagate JSON Schema `description` to Pydantic `Field.description`
  - #18 — `assistant export` should run `discover_tools` for host-harness manifests
  - #19 — detect parameter/body name collisions in `_build_args_schema`

## Landing the Plane (Session Completion)

**When ending a work session**, complete ALL steps below. Work is NOT
complete until `git push` succeeds.

1. **File issues for remaining work** — anything follow-up worthy
2. **Run quality gates** (if code changed) — match CI scope:
   - `uv run pytest tests/`
   - `uv run ruff check src tests`
   - `uv run mypy src tests`  (CI runs the broader scope; `mypy src/` alone misses test-side errors)
   - `openspec validate --strict` if OpenSpec artifacts changed
3. **Update issue / OpenSpec status** — close finished, annotate in-progress
4. **PUSH TO REMOTE** — mandatory:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
   If the session touched a persona submodule, use
   `scripts/push-with-submodule.sh` so the parent never references an
   unreachable submodule SHA.
5. **Clean up** — clear stashes, prune remote branches
6. **Hand off** — provide context for the next session

**Rules:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing — that leaves work stranded locally
- If push fails, resolve and retry until it succeeds
