# eval-simulation-loop — Design

## Context

Roadmap P27 (ecosystem pillar 5). Inputs: the gen-eval assets under
`evaluation/` (descriptors, scenarios, `bin/assistant-quiet`), the
test-only mock corpus (`tests/mocks/graph_client.py`,
`tests/fixtures/graph_responses/`, pytest-httpserver suites), the
`http_tools` discovery layer (P3), Langfuse tracing (P4), and the
P21 post-turn interaction capture. Constraint: ADR 0006 — gen-eval is
a CONSUMER of this repo, never a dependency; fresh clones and CI must
stay green without sibling checkouts.

## Decisions

### D1 — Generic fixture-backed simulator behind the existing discovery seam

One small FastAPI app (`src/assistant/simulation/server.py`; fastapi
is already a core dependency for the AG-UI bridge) serves canned JSON
responses described by per-source `routes.yaml` manifests. Each source
becomes a mounted sub-app at `/<source_name>` exposing its own
FastAPI-generated `/openapi.json` with explicit `operationId`s —
exactly the document shape `discover_tools` already fetches at
`{base_url}/openapi.json`. Declared query parameters are surfaced via
a dynamic endpoint `__signature__`, so the http_tools builder derives
a real args schema while the response stays canned. Consequence: the
simulator is invisible to agent code — simulation = persona config +
env vars, no new code paths.

Alternatives rejected: replaying via pytest-httpserver (test-scoped
lifecycle, not a runnable operator surface); per-service bespoke mock
apps (the manifest format makes new corpora data, not code).

### D2 — Simulation persona lives in `evaluation/simulation/personas/`

Not `personas/_simulation/` — the repo-root `personas/` mount is
reserved for private submodules, `_`-prefixed directories are skipped
by `PersonaRegistry.discover()`, and a public persona there would blur
the execution-boundary rule the privacy guard protects. Not
`tests/fixtures/personas/` — that root is the privacy-guarded *test*
corpus; the sim persona is a *runtime* eval surface and adding it
there would couple gate runs to test-internal conventions. The
existing `ASSISTANT_PERSONAS_DIR` env seam (G6) loads it with zero
registry changes. The persona's `tool_sources` use the standard
`base_url_env` indirection with a `SIM_<SOURCE>_URL` naming convention
shared between `assistant simulate` (prints export lines) and
`run-gate.sh` (derives them from the sources directory).

Sources simulate the *real* source names roles bind to
(`content_analyzer`, `coding_tools`) so `DefaultToolPolicy`'s
`preferred_tools` filtering admits the simulated tools per role;
`ms_graph` demonstrates promoting the graph-responses corpus verbatim
(sentinel comment lines stripped at load).

### D3 — `assistant simulate` is minimal by design

Loopback bind (non-loopback warns, mirroring `serve`), fixture root
defaulting to `evaluation/simulation/sources`, prints the exact
`export` lines + follow-up invocation, then blocks in `uvicorn.run`.
Lifecycle for eval runs is owned by the simulation descriptor's
`startup:` block (same detachment pattern as the serve descriptor),
not by the gate script.

### D4 — Eval gate is an external shell-out with advisory-skip default

`evaluation/run-gate.sh` locates gen-eval via `GEN_EVAL_PROJECT`
(default: sibling `agentic-coding-tools/packages/gen-eval`), exports
the simulation env, and runs each scenario file through
`uv run --project <gen-eval> gen-eval run --descriptor ... --scenario ...`,
exiting nonzero on any failure. When gen-eval is absent — directory
missing OR present but not runnable (offline environments carry a
lock-resolution stub of the package with no console script; a
`gen-eval --help` probe distinguishes availability failures from
scenario failures) — it SKIPs with exit 0 and a message naming
ADR 0006 — advisory by default because standalone clones/CI must stay
green — with `EVAL_GATE_REQUIRE=1` as
the strictness opt-in (G7-style, inverted: G7 defaults strict because
tests silently skipping is a trap; the gate defaults advisory because
a hard dependency on a sibling checkout is the exact ADR 0006
failure). A `python -m assistant.simulation.gate` module was rejected:
it would put gen-eval invocation knowledge inside the package,
drifting toward the cross-repo coupling the ADR forbids.

### D5 — Trace→dataset export is offline-first (persona DB, not Langfuse API)

`assistant export-eval-dataset` reads the persona DB `interactions`
table (written by P21 post-turn capture) via the new
`MemoryManager.list_interactions()` and emits gen-eval scenario YAML
**stubs** through pure functions in `simulation/dataset.py`. Stubs
carry provenance (`source:` block), a `todo` marker, and a placeholder
`/chat` replay step; a human completes message + expectations before
promoting a stub into a suite — the propose → eval → human-approved
loop applied to the dataset itself. Default output
`evaluation/datasets/exported/` is git-ignored and outside every
`scenario_dirs` (raw exports may contain private interaction
summaries; incomplete stubs must not poison gate runs).

**Follow-up (recorded, out of scope)**: Langfuse-API export — pull
full traces (messages, tool calls, scores) via the Langfuse Python SDK
to generate complete scenarios instead of stubs. Requires network +
credentials; the offline path stays as the floor.

### D6 — Per-role suites start at the credential-free floor

`sim-role-compose-sweep.yaml` runs `assistant export -p sim -r <role>
-H claude_code` per public role (full persona × role composition +
host-seat capability resolution, deterministic, no LLM);
`sim-tool-discovery.yaml` runs `assistant run -p sim --list-tools`
(exit code is already all-sources-discovered semantics). LLM-driven
behavioral scenarios per role (tool *selection* under simulation)
layer on later — they need model credentials and gen-eval-side judge
support, and P20 local inference makes them cheap; nothing in the
format blocks adding them as more scenario files.

### D7 — Telemetry vocabulary extension

`list_interactions` is traced as `op="interaction_list"`, added to the
closed `_VALID_OPS` set (observability spec MODIFIED). Reusing an
existing op value was rejected: the vocabulary exists precisely so
dashboards can key on operation identity.

## Risks / Trade-offs

- **gen-eval scenario/descriptor schema drift**: the suites use only
  step shapes already exercised by the existing descriptors
  (`transport: cli`, `args`, `exit_code`/`not_empty`); the gate script
  is the single integration point to fix if the CLI contract changes.
- **Simulator fidelity**: canned responses ignore request params. This
  is deliberate (deterministic evals); stateful simulation is out of
  scope until a scenario needs it.
- **Root `/health` is also an OpenAPI operation** on the root app; it
  is never a tool source unless someone points a source at the root
  URL — harmless, and useful for descriptor health checks.

## Migration

None. Additive surface; existing personas, tests, and eval assets are
untouched (the ms_graph seed corpus is a copy, not a move).
