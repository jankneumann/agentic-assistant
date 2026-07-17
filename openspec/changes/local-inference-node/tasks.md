# local-inference-node — Tasks

## 1. Endpoint health

- [x] 1.1 `core/capabilities/health.py` — `EndpointHealth` config
  (+ `parse_endpoint_health` validation), three-valued
  `HealthStatus`, `EndpointHealthMonitor` (TTL cache, injectable
  clock, async `probe`/`refresh`, shared default monitor)
- [x] 1.2 `core/capabilities/models.py` — `ModelRef.health` field;
  `parse_model_registry` accepts `health:` (rejects it on
  endpoint-less entries); `RegistryModelProvider` health filter on
  both resolution paths with fail-closed empty-chain error
- [x] 1.3 Daemon pre-warm — `assistant daemon` refreshes health state
  for health-declaring entries before the scheduler starts
  (error-swallowed, no-op without `health:` entries)

## 2. Local embeddings

- [x] 2.1 `core/graphiti.py` — `RegistryEmbedder` (graphiti
  `EmbedderClient` over `OpenAICompatibleClient`), explicit
  `embeddings` binding resolution (health-aware, guardrail-gated),
  `Graphiti(embedder=...)` wiring, disable-Graphiti-on-unhonorable-
  binding degradation

## 3. Catalog sync

- [x] 3.1 `core/capabilities/catalog.py` — D9-postured
  `fetch_catalog`, cache write/load
  (`<persona_dir>/.cache/models/catalog.json`),
  `apply_catalog_metadata` merge (declared values win)
- [x] 3.2 `core/persona.py` — apply cached catalog metadata to the
  parsed registry at load (offline-safe no-op without a cache)
- [x] 3.3 `cli.py` — `models` group: `sync-catalog` (persona-scoped
  `OPENROUTER_API_KEY`, `--url` override, clear no-network error) and
  `check-health` (per-entry verdicts, exit 1 on any unhealthy)

## 4. Config + docs

- [x] 4.1 `personas/_template/persona.yaml` — GX10 node example:
  chat + embedding entries (`local-only`/`private-data-ok`/`cheap`
  tags, `health:`), `scheduler`/`memory`/`embeddings` bindings,
  fleet-story comments
- [x] 4.2 `docs/deployment/gx10-node.md` — endpoint setup pointers
  (NIM / vLLM / Ollama), registry snippet, verification commands
- [x] 4.3 CLAUDE.md — local-inference/fleet section + "What's Not Yet
  Wired" update

## 5. Tests

- [x] 5.1 `tests/test_endpoint_health.py` — health config parsing +
  validation errors; monitor probe (httpx.MockTransport), TTL expiry,
  exempt entries; resolution skip-unhealthy → fallback, UNKNOWN
  eligible, fail-closed on all-unhealthy private chain, no network on
  sync resolve
- [x] 5.2 `tests/test_graphiti_embedder.py` — embedder wiring
  (binding → `embedder=` kwarg; no binding → unchanged call), wire
  shape of `RegistryEmbedder.create`/`create_batch`, degradation on
  unhonorable binding, guardrail denial propagation
- [x] 5.3 `tests/test_catalog_sync.py` — fetch (auth header, redirect
  refusal, size cap, network-error mapping), cache round-trip, merge
  semantics (empty-only fill), persona-load integration, CLI
  `sync-catalog`/`check-health` behaviors
- [x] 5.4 Template example parse test — the commented `models:` block
  in `personas/_template/persona.yaml` uncomments to a valid registry
- [x] 5.5 Full gates: `uv run pytest tests/`, `uv run ruff check src
  tests`, `uv run mypy src tests`, `openspec validate
  local-inference-node --strict`
