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
uv run assistant serve -p personal --a2a           # + A2A surface (agent card, /a2a/v1)
uv run assistant serve -p personal --mcp           # + MCP surface (streamable HTTP at /mcp)
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

# Local inference / model registry (P20)
uv run assistant models check-health -p personal   # probe health:-declaring registry entries
uv run assistant models sync-catalog -p personal   # cache OpenRouter pricing metadata

# Clean-room knowledge sharing (P26)
uv run assistant cleanroom export -p personal --to work   # declassify memory into a share bundle
uv run assistant cleanroom import -p work <bundle.json>   # ingest a verified bundle
uv run assistant cleanroom revoke -p personal <bundle-id> # source-persona revocation
uv run assistant cleanroom sync -p work                   # purge imports of revoked bundles

# Continual learning (P28) — needs a persona `learning:` section
uv run assistant feedback -p personal "too wordy"         # store human feedback (also: REPL /feedback)
uv run assistant reflect -p personal                      # consolidate interactions into memory
uv run assistant learning collect -p personal             # machine collectors (eval/budget/breaker/cost)
uv run assistant learning propose -p personal             # feedback -> proposal files (reviewable diffs)
uv run assistant learning apply -p personal <id> [--approved]  # eval-gated, guardrail-gated apply

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
- `src/assistant/core/toolspec.py` — `ToolSpec`, the single internal,
  harness-neutral tool representation (MCP-shaped: name, description,
  JSON-Schema `input_schema`, async `handler`, `source` provenance;
  P17 `mcp-server-exposure`). Every tool source compiles into it:
  extensions via `Extension.tool_specs()`, OpenAPI-derived HTTP tools
  via the `http_tools` builder. `ToolPolicy.authorized_tools()` is the
  SOLE aggregator (telemetry-wrapped there via
  `wrap_extension_tool_specs`); harnesses render the list through the
  per-harness adapters in `src/assistant/harnesses/tool_adapters.py`
  (LangChain `StructuredTool`, MSAF `FunctionTool`, `mcp.types.Tool`)
  and never derive tools from extensions. Argument validation lives in
  the handler (`tool_spec_from_model`), so every surface — including
  direct MCP dispatch — validates identically.
- `src/assistant/extensions/` — extension implementations. The
  Extension protocol is `name` + `tool_specs() -> list[ToolSpec]` +
  `health_check()` — the legacy `as_langchain_tools()` /
  `as_ms_agent_tools()` dual surface was REMOVED in P17 (tool-spec
  exit criterion; no shim retained — out-of-tree structural extensions
  must implement `tool_specs()`). Since P10 `extension-lifecycle`, extensions may implement
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

## Harness Routing (P11)

`--harness auto` is the CLI default on `run` / `serve` / `daemon`:
`select_harness(persona, role)` in `harnesses/factory.py` resolves it
deterministically — NO LLM calls (semantic task routing is P12, not
this seam). Precedence:

1. **Explicit `-H <name>`** always wins (bypasses routing entirely).
2. **Persona `harnesses.routing:` rules** (parsed at persona load
   onto `PersonaConfig.harness_routing` by `core/harness_routing.py`;
   the `routing` key is popped out of the `harnesses` mapping).
   Ordered first-match on `role:` (role-name glob) and/or `tools:`
   (globs over the role's `preferred_tools`; `ms_graph:*` matches the
   full source:operation string, bare `ms_graph` matches the source
   prefix). A matching rule with a disabled target is skipped with a
   WARNING; unknown/host targets raise.
3. **Built-in defaults**: role prefers MS-source tools
   (`ms_graph`/`outlook`/`teams`/`sharepoint`) AND
   `ms_agent_framework` enabled → MSAF; else `deep_agents`; else the
   remaining enabled SDK harness; else an actionable error.

**Host harnesses are never auto-selected** — they export config
rather than execute, so the host/subscription tier stays explicit
(`-H claude_code` + `assistant export`). Every decision emits a
`harness.routing` span (start_span escape hatch) + INFO log line.
Scheduled jobs may pin a per-job `harness:` (or `auto`) — it beats
the daemon `-H`; the REPL routes once at startup (`/role` keeps the
session's harness).

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

## A2A Server (P6)

`assistant serve --a2a` mounts the A2A agent↔agent protocol surface
(guiding principle 7: A2A is the adopted agent↔agent standard)
alongside AG-UI on the same loopback-default server:

- **Agent card**: `GET /.well-known/agent-card.json` (A2A 0.3.0
  canonical) and legacy `GET /.well-known/agent.json` — same card at
  both paths; built from persona + enabled roles (one skill per role),
  `capabilities.streaming=true`.
- **JSON-RPC**: `POST /a2a/v1` with `message/send` (blocking; returns
  the terminal Task) and `message/stream` (SSE; each `data:` line is a
  JSON-RPC envelope wrapping one A2A event). REST-style alias:
  `POST /a2a/v1/message:stream` (bare MessageSendParams in, bare
  events out).
- **Sessions**: A2A `contextId` ≡ session `thread_id`; the in-memory
  `SessionRegistry` (`src/assistant/a2a/task_handler.py` — first
  consumer of the harness-adapter Session Registry requirement)
  creates a FRESH harness+agent per context, reuses known contextIds,
  and REJECTS unknown ones (durable/resumable sessions wait on the
  Postgres checkpointer).
- **Approval bridge**: a guardrail approval denial
  (`ModelCallDeniedError`, P13 deny-until-interrupt) surfaces as task
  state `input-required` before the final `failed` update —
  observational only until interrupt/resume lands.
- **Types are hand-rolled** in `src/assistant/a2a/types.py`
  (spec-shaped, camelCase wire aliases); adopt the official `a2a-sdk`
  later — migration is a mechanical import swap. The HarnessEvent→A2A
  mapping lives in `src/assistant/transports/a2a/mapper.py` (sibling
  of the AG-UI mapper; AG-UI untouched).
- **Deferred**: `tasks/get`/`tasks/cancel`, push notifications,
  multi-turn task continuation, file/data parts (rejected with
  -32005). Agent-card auth landed with P25 (see Agent IAM below).

## Agent IAM (P25)

`agent-iam` adds identity & access management with an explicit
inbound/outbound split (AgentCore Identity lesson):

- **`AgentIdentity` principal**
  (`core/capabilities/identity.py`): frozen dataclass (persona, role,
  `delegation_chain` tuple, session/thread id, issued_at) — a
  SPIFFE-shaped placeholder. Optional `ActionRequest.identity` field
  (default None; old call sites unchanged), populated by the
  delegation spawner, `check_model_call` (synthesized from
  persona/role when not injected), and both harnesses'
  `spawn_sub_agent` delegate checks (DeepAgents gained the check,
  mirroring MSAF).
- **Delegation chains are attributable + bounded**: each hop derives
  the child via `identity.delegate_to(sub_role)`; the spawner
  enforces `guardrails.delegation.max_chain_depth` (default 5, 0 =
  unlimited — applied even without a `guardrails:` section) and logs
  the chain on every decision. `PolicyGuardrails` policies gained
  identity dimensions: `role:` glob (acting role) and
  `min_chain_depth:` (skips identity-less requests) — additive to
  action_type/resource globs.
- **Inbound A2A auth**: persona `auth.a2a: {type: bearer, token_env:
  REF}` (ref resolved through the CredentialProvider seam, never raw
  env). Missing/wrong token → HTTP 401 + `WWW-Authenticate: Bearer`
  on `POST /a2a/v1` and the REST alias (HTTP-level, not JSON-RPC);
  the card stays public and advertises `securitySchemes` +
  `security`. No declaration → loopback-unauthenticated with a
  startup WARNING; declared-but-unresolvable token → startup error.
  MCP-surface auth is a recorded P17 integration follow-up.
- **Outbound OpenBao backend**
  (`core/capabilities/openbao.py`): thin httpx client (no hvac) for
  the P24 CredentialProvider seam — persona `credentials: {backend:
  openbao, url_env, role_id_env, secret_id_env, mount}`. KV v2 read
  at `<mount>/data/<persona>/<ref>` (data key `value`) mirrors the
  P13 `.env` namespace 1:1 (present wins even when empty; 404 falls
  through to persona `.env` → process env); AppRole login with
  proactive token re-acquisition before TTL expiry;
  unconfigured/unreachable OpenBao degrades to the env tiers with one
  WARNING — never fatal. Wired via the P13
  `credential_provider_factory` injection point (an injected factory
  still wins). No OpenBao server exists in dev/CI — tests are
  `httpx.MockTransport`-mocked.
- **Audit trail**: every identity-carrying guardrail decision emits a
  `guardrail.decision` span (`core/capabilities/audit.py`) through
  the telemetry `start_span` escape hatch — no new trace op, no
  separate audit store (deferred with approval interrupt/resume).

## Knowledge Clean Room (P26)

`knowledge-clean-room` adds the declassification gateway
(`core/cleanroom.py`) — the RUNTIME analogue of the ADR-0004
test-time privacy boundary. Policy-driven, audited flow: source
persona memory → share rules → sanitization profile → provenance
envelope (share bundle) → shared space → accept rules → consuming
persona.

- **No config, no sharing**: a persona without a `clean_room:`
  section (see `personas/_template/persona.yaml`) can neither export
  nor import — total isolation stays the default. `share:` rules
  (first rule naming the audience wins) pick kinds
  (facts/preferences/interactions), key/content globs (exclusions
  win), preference categories, a sanitization profile, and an
  audience (persona names and/or `external`). `accept:` rules (first
  `from:` glob match wins) pick trusted sources, kinds, and profiles.
- **Sanitization profiles** layer PII patterns (email/SSN/card/IP/
  phone) ON TOP of the reused `telemetry/sanitize.py` secret chain:
  `standard` (default) = secrets + PII; `secrets` = secret chain
  only. The telemetry module is untouched (its 15-pattern list is
  observability-spec-bound).
- **Bundles** are self-contained JSON (`.cleanroom/<audience>/
  <bundle_id>.json`, git-ignored; `space_dir:` overrides): per-item
  content hashes + whole-bundle hash (tamper evidence, not
  signatures), exporter `AgentIdentity`, profile, timestamps. The
  bundle format IS the external-agent interop surface for now —
  A2A/MCP transport is a recorded follow-up.
- **Import quarantines everything as facts**: accepted items land as
  provenance-wrapped facts under `cleanroom/<bundle_id>/<item_id>`
  keys (foreign preferences never become native preferences).
  **Revocation**: source persona only (`cleanroom revoke`); import
  refuses revoked bundles; `cleanroom sync` purges already-imported
  items via `MemoryManager.delete_facts_by_prefix`.
- **Guardrails + audit**: export/import are guardrail actions
  (`cleanroom_export`/`cleanroom_import`; `require_confirmation`
  DENIES until the approval interrupt flow exists — P13 semantics).
  Every op emits an identity-stamped `cleanroom.<op>` span via the
  `start_span` escape hatch (P25 precedent). `MemoryManager` gained
  `list_facts`/`list_preferences`/`delete_facts_by_prefix` and the
  `trace_memory_op` vocabulary gained
  `fact_list`/`preference_list`/`fact_delete`.
- Tests run between the two fixture personas `cleanroom_alpha`/
  `cleanroom_beta` (`tests/fixtures/personas/`) with an in-memory
  `CleanRoomMemoryStore` fake — the public suite stays DB-free.

## Continual Learning (P28)

`continual-learning` adds the FeedbackEvent → ImprovementProposal
pipeline (`core/learning.py`) — memory that grows, behind the roadmap
constraint **propose → eval → human-approved diff, NEVER self-merge**:

- **No config, no learning**: a persona without a truthy `learning:`
  section (see `personas/_template/persona.yaml`) refuses every entry
  point — feedback, collectors, reflection, propose, apply (clean-room
  posture). Keys: `enabled`, `auto_apply_low_risk` (default false),
  `reflection.consumer` (models binding, default the reserved
  `memory` key), `proposals_dir` (default `<persona>/proposals`).
- **FeedbackEvent** (closed sources `human|eval|guardrail|resilience|
  cost|critique`): human capture via `assistant feedback` (`--prefer
  cat:key=value` distills preferences) + REPL `/feedback`; stored as
  interactions with `metadata.source=feedback`. **Machine collectors
  read what already exists** — run-gate output (FAIL/SKIP/PASS
  lines), budget-ledger utilization ≥ 80%, the new read-only
  `CircuitBreakerRegistry.breakers()` snapshot, unpriced cloud
  registry entries under a budget — on demand (`assistant learning
  collect`) or as scheduler jobs; no new daemons.
- **Reflection** (`assistant reflect`, or a `kind: reflect`
  `schedules:` job — role/prompt optional, daemon validates learning
  + database_url up front): watermark-filtered interactions →
  summary (model-backed via `OpenAICompatibleClient` under the
  reflection consumer binding when an openai-compatible endpoint
  resolves, deterministic digest otherwise) → provenance-stamped
  `learning/reflection/<ts>` fact + Graphiti episode write-back via
  `store_episode` (closes the deferred P21 follow-up).
- **Proposals are FILES** under the persona `proposals/` dir (the
  submodule diff IS the approval workflow). Risk tiers by kind:
  preference=LOW, prompt_layer=MEDIUM, routing_config=HIGH.
  `assistant learning apply` gates in order: `learning_apply`
  guardrail action (deny AND require_confirmation refuse — P13
  semantics until P30), the P27 eval gate (SKIP counts as pass with a
  warning; nonzero refuses), then LOW-or-`--approved`. preference →
  `MemoryManager.store_preference` (new; `trace_memory_op` gained
  `preference_write`); prompt_layer → appended suggestion block
  (path-escape refused); routing_config → review-only, always
  human-applied. ONLY preference+LOW may auto-apply, only under
  `auto_apply_low_risk: true`, through the same full gate chain.
- **Audit**: `learning.<feedback|reflect|propose|apply>` spans via the
  `start_span` escape hatch, identity-stamped (P25/P26 precedent).
- Tests: fixture persona `learning_lab` + in-memory
  `FakeLearningStore`; the memory-manager seam for CLI/scheduler is
  `assistant.core.learning._learning_memory_manager` (patch there, G4).

## Local Inference & Fleet (P20)

Local OpenAI-compatible endpoints (GX10 via NIM / vLLM / Ollama — or
any host) are first-class model-registry citizens; quickstart in
[docs/deployment/gx10-node.md](docs/deployment/gx10-node.md), fleet
rationale in the 2026-07-07 architecture review §1:

- **Registry entries**: nothing schema-new for the endpoint itself —
  dialect `openai-compatible` + `endpoint` (P19). P20 adds an optional
  per-entry `health:` block (`path` default `/models`, `timeout` 2 s,
  `ttl` 60 s; requires an `endpoint`).
- **Health-checked resolution** (`core/capabilities/health.py`):
  `EndpointHealthMonitor` probes async and caches verdicts;
  `RegistryModelProvider.resolve` consults the cache only (sync path
  never probes). Fresh-unhealthy entries are skipped → fallback chain
  proceeds to cloud; never-probed/stale = eligible (optimistic — the
  bind-time fallback walk still covers a dead node). **Fail-closed**:
  when health filtering empties a tag-satisfying chain (e.g. all
  `private-data-ok` entries down), resolution raises — privacy never
  silently falls back to cloud. Pre-warm: `assistant models
  check-health` and daemon startup.
- **Local embeddings**: an **explicit** `embeddings` binding (the
  `default` key never spills into it) makes `create_graphiti_client`
  pass a `RegistryEmbedder` (graphiti `EmbedderClient` over the P19
  raw `OpenAICompatibleClient`; budget-gated, persona-scoped
  credentials) so semantic memory search embeds locally. Declared but
  unhonorable binding → Graphiti disabled (Postgres-only memory), not
  a silent cloud embedder. `memory` is a reserved binding key for the
  P21 summarization consumer (not yet dispatched on).
- **Catalog sync** (`core/capabilities/catalog.py`): `assistant
  models sync-catalog -p <persona>` fetches OpenRouter `/models` (D9
  posture: no redirects, 10 MiB cap; key ref `OPENROUTER_API_KEY`
  optional) into git-ignored
  `<persona_dir>/.cache/models/catalog.json`; on persona load,
  entries with a matching `id` inherit pricing/context_length/
  modalities for fields they left empty — declared values win,
  missing cache is a silent no-op (load never touches the network).

## MCP Server (P17)

`assistant serve --mcp` exposes the assistant as an MCP server
(complementary to A2A — different protocol, different clients;
protocol-standards analysis 2026-07-16) on the same loopback-default
server:

- **Transport**: official `mcp` Python SDK, low-level `Server` +
  `StreamableHTTPSessionManager(stateless=True, json_response=True)`
  mounted at `POST /mcp` by `make_app(..., enable_mcp=True)`
  (`src/assistant/mcp/server.py`; the lifespan holds
  `session_manager.run()` open). Every POST is self-contained — no
  MCP transport session; plain JSON responses.
- **Tools**: one `ask_<role>` per enabled role plus a generic `ask`
  bound to the serving role (`ask` and `ask_<serving-role>` share a
  registry, so contexts are interchangeable). The persona's own tool
  inventory is NOT re-exported — callers delegate tasks; the
  assistant's ToolPolicy governs what *it* calls. `tools/list` is a
  pure `render_mcp_tools` rendering of MCP-shaped ToolSpecs (no
  translation layer); `tools/call` validates args against
  `inputSchema` and maps handler errors to `isError` results.
- **Sessions**: tool argument `context_id` ≡ session `thread_id`
  (mirrors A2A `contextId`). Missing → fresh session (same
  `create_harness` + agent pipeline as `/chat` and A2A, one per-role
  `SessionRegistry`); known → reuse (per-session lock serializes
  turns); unknown/expired → rejected as a tool error (in-memory
  registry; durable sessions still deferred).
- **Every result** carries `{response, context_id}` as structured
  content — pass `context_id` back to continue the conversation.
- **Deferred**: MCP resources/prompts/elicitation, streaming task
  updates over MCP, transport auth (OAuth 2.1 / MCP authorization
  spec — P25; keep the default loopback bind until then).

## Meta-Harness Compat & Sandbox (P22)

`meta-harness-compat` implements ADR 0007 (compose UNDER
meta-harnesses; docs/deployment/meta-harness.md):

- **Omnigent export**: `assistant export-omnigent-agent -p <persona>
  [--base-url ...] [-o file]` renders an Omnigent-SHAPED agent
  definition (`src/assistant/composition/omnigent.py`) describing the
  assistant as an external/custom agent composed via the served
  A2A/MCP/AG-UI endpoints — never spawned as a CLI subprocess. The
  YAML header + `schema_verified: false` mark it unverified against
  the canonical omnigent-ai/omnigent schema (offline design; verify
  on a connected machine before registering).
- **First real SandboxProvider**: `ContainerSandboxProvider`
  (`core/capabilities/sandbox.py`) compiles the sandbox-provider
  spec's three planes into `docker run`/`podman run` argv (runtime
  autodetected, `ProcessRunner` injectable — tests never execute a
  real container; opt-in smoke via
  `RUN_CONTAINER_SANDBOX_TESTS=1 pytest
  tests/integration/test_container_sandbox_smoke.py`). Plane types
  (`FilesystemPlane`/`NetworkPlane`/`CredentialsPlane`) live on
  `SandboxConfig` (types.py); `PassthroughSandbox` carries declared
  planes on context metadata without enforcing. LIMITATION: a
  non-empty network allow-list compiles to `SANDBOX_NET_ALLOW`/proxy
  env vars (plain container runtimes can't filter per-host egress —
  pair with an egress proxy or NemoClaw/OpenShell policy); an empty
  allow-list IS enforced (`--network=none`).
- **Seam**: `SandboxedProcessRunner` is the
  extension-subprocess-boundary enforcement point — extensions
  spawning subprocesses should go through it, posture always from the
  ExecutionContext. Tool-invocation-boundary container enforcement is
  deferred until a workload needs it.
- **Selection**: persona `sandbox:` section (annotated schema in
  `personas/_template/persona.yaml`) → resolver picks
  `ContainerSandboxProvider` only for `provider: container`;
  personas without the section keep `PassthroughSandbox`. Requested-
  but-unconstructible container sandbox FAILS (no silent passthrough
  degrade). NemoClaw/OpenShell deployment on the GX10 is deferred to
  P23 (ADR 0007 records what it requires from us).

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
  return `[]` from `tool_specs()`. The four MS extensions
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
  keys resolve through the `CredentialProvider` seam. P20
  `local-inference-node` added the OpenRouter catalog **sync** and
  health-checked local (GX10) entries — see "Local Inference & Fleet"
  above. Still deferred: the MSAF binding covers `openai-compatible`
  refs only (no connector packages for the other dialects).
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
  graphiti, MSAL); the OpenBao production backend landed in P25 (see
  the Agent IAM section).
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
