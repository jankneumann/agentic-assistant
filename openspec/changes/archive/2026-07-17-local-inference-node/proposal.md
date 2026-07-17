# local-inference-node — Local OpenAI-Compatible Endpoints as First-Class Registry Citizens (P20)

## Why

The P19 model registry already *describes* local backends — dialect
`openai-compatible` plus an `endpoint` fully names a vLLM / Ollama /
NIM server on the GX10 (model-provider spec, "ModelRef captures a
local endpoint") — but nothing makes them *reliable* citizens of the
fleet (arch-review G-B, ecosystem pillar 1):

- Resolution is blind to endpoint liveness: a powered-down GX10 entry
  is tried first on every dispatch and only fails at bind time; a
  fallback chain exists but there is no way to skip a known-dead
  local node — and, dually, no guarantee that a privacy-constrained
  request (`local-only` / `private-data-ok`) refuses to run rather
  than silently landing on cloud when the local node is down.
- The P19 raw OpenAI-compatible embeddings binding exists but nothing
  consumes it: Graphiti semantic memory search still embeds through
  graphiti-core's default (cloud OpenAI) path even when the persona
  declares a local embedding endpoint.
- Registry entries must hand-copy OpenRouter pricing metadata; the
  catalog **sync** deferred from P19 never landed, so cost attribution
  and budget gating run on stale or absent pricing.

## What Changes

- **Endpoint health checks** (`core/capabilities/health.py`): registry
  entries may declare an optional `health:` block (`path`, `timeout`,
  `ttl`). An `EndpointHealthMonitor` probes `GET <endpoint><path>`
  asynchronously and caches the verdict with a TTL;
  `RegistryModelProvider.resolve` consults the *cached* state only —
  the sync resolve path never blocks on a probe. Entries with a fresh
  negative verdict are skipped so the fallback chain proceeds to
  cloud; when health filtering would empty a tag-satisfying chain,
  resolution fails closed with `ModelResolutionError` (privacy tags
  never silently fall back to cloud — health filtering can only
  remove candidates, never re-admit entries lacking required tags).
  Pre-warm points: `assistant models check-health`, daemon startup,
  and programmatic `EndpointHealthMonitor.refresh()`.
- **Local embeddings for semantic memory**
  (`core/graphiti.py`): when a persona's `models:` registry declares
  an explicit `embeddings` consumer binding, `create_graphiti_client`
  resolves it (health-aware) and passes a `RegistryEmbedder` — a
  graphiti-core `EmbedderClient` adapter over the P19 raw
  `OpenAICompatibleClient` (budget-gated, credential-seam-resolved) —
  so Graphiti episodes and semantic search embed on the local node.
  No binding → current behavior, byte-for-byte. A binding that is
  declared but cannot be honored disables Graphiti for that persona
  (warning + Postgres-only degradation) rather than silently
  embedding through the default cloud path.
- **OpenRouter catalog sync** (`core/capabilities/catalog.py` +
  `assistant models sync-catalog`): fetches the OpenRouter `/models`
  catalog (API key via the persona-scoped `CredentialProvider`;
  http_tools D9 posture — no redirects, 10 MiB streaming cap, TLS
  verification) into a git-ignored persona-local cache file
  (`<persona_dir>/.cache/models/catalog.json`). At persona load,
  registry entries whose `id` matches a cached catalog row inherit
  `pricing` / `context_length` / `modalities` for any field they left
  empty — declared values always win. Entirely optional and
  offline-safe: no cache file → nothing happens; no network at sync
  time → a clear CLI error and nothing else breaks.
- **CLI `models` command group**: `assistant models sync-catalog -p
  <persona> [--url]` and `assistant models check-health -p <persona>`
  (probes every health-declaring entry, prints per-entry verdicts,
  exits non-zero when any endpoint is unhealthy — the documented GX10
  verification command).
- **Template + docs**: `personas/_template/persona.yaml` gains a
  GX10-node example (chat + embedding entries with `local-only` /
  `private-data-ok` / `cheap` tags, `health:` blocks, and
  `scheduler` / `memory` / `embeddings` consumer bindings);
  `docs/deployment/gx10-node.md` quickstart; CLAUDE.md fleet section.

## Out of Scope

- Actual GX10 provisioning / NIM container management — P23
  `deployment-topology` owns the home-lab topology.
- Mid-turn memory retrieval routing and Graphiti episode write-back —
  P21 follow-ups, unchanged here.
- A background health-probe scheduler loop (probes are pre-warmed at
  daemon startup and refreshable on demand; a periodic re-probe job
  can ride the P7 scheduler later without new machinery).
- OpenRouter catalog *auto*-sync on persona load (explicit CLI sync
  only — persona load stays offline-deterministic).
- Chat-path wiring of the `memory` consumer binding (the binding key
  is reserved and documented; the P21 summarization consumer that
  would dispatch on it is future scope).

## Impact

- Affected specs: `model-provider` (ADDED: endpoint health
  configuration, health-filtered resolution, catalog cache),
  `memory-policy` (ADDED: embeddings consumer binding for Graphiti),
  `cli-interface` (ADDED: `models` command group).
- Affected code: `src/assistant/core/capabilities/{models,health,
  catalog}.py`, `src/assistant/core/{graphiti,persona}.py`,
  `src/assistant/cli.py`, `personas/_template/persona.yaml`, tests,
  docs.
- No new runtime dependencies (httpx covers probes and the catalog
  fetch; graphiti-core — already a dependency — supplies the
  `EmbedderClient` ABC).
- No breaking changes: `health:` is optional, the `embeddings`
  binding is opt-in, the catalog cache is absent by default.
