# local-inference-node — Design

The P19 contracts (`openspec/specs/model-provider/spec.md`) are
binding; this document records the judgment calls made while making
local endpoints health-checked, privacy-safe, and metadata-complete.

## D1: Health state is three-valued and resolution is optimistic

`EndpointHealthMonitor.status(ref)` returns one of:

| State | Condition | Resolution effect |
|-------|-----------|-------------------|
| HEALTHY | entry declares no `health:` block (exempt), or the cached probe verdict is positive and younger than `ttl` | eligible |
| UNKNOWN | `health:` declared but never probed, or the cached verdict is older than `ttl` | eligible (optimistic) |
| UNHEALTHY | cached probe verdict is negative and younger than `ttl` | skipped |

Only a *fresh negative* verdict removes an entry from the chain.
Rationale: the sync `resolve()` path must never block on a network
probe (it runs inside `create_agent`), so at first use the state is
necessarily UNKNOWN — treating UNKNOWN as ineligible would make every
health-checked entry unusable until something probes it, inverting
the feature's purpose. Correctness is not lost: the bind-time
fallback walk (P19) already survives a dead endpoint; health
filtering is a latency/ordering optimization that prunes *known*-dead
entries, and the fail-closed guarantee (D2) rests on tag filtering,
which is unconditional.

Cache entries are keyed by registry entry name and stamped with
`time.monotonic()`; the monitor takes an injectable clock for TTL
tests. A module-level default monitor is shared by all
`RegistryModelProvider` instances of a process (mirroring the
graphiti/engine cache pattern) so a CLI probe or daemon pre-warm
benefits every subsequent resolution; tests reset it via
`_reset_default_health_monitor()`.

## D2: Fail-closed falls out of filter ordering

Health filtering runs *after* required-tag filtering and can only
remove candidates — it never re-admits an entry that lacks a required
tag. Consequently, when a request requires `local-only` /
`private-data-ok` and every tag-satisfying entry is UNHEALTHY, the
filtered chain is empty and `resolve()` raises `ModelResolutionError`
naming the unhealthy entries — there is no code path on which the
request reaches a cloud entry without those tags. The same rule
applies uniformly to all tags (not just the privacy pair): an empty
post-health chain always raises rather than silently substituting.

## D3: Pre-warm / lazy probe semantics (recorded per mission)

Probes are async (`EndpointHealthMonitor.probe` / `.refresh`, plain
httpx GET, 2xx == healthy, everything else — including connect errors
and refused redirects — unhealthy). Nothing probes implicitly on the
resolve path. Pre-warm points:

1. `assistant models check-health -p <persona>` — operator-facing
   verification; also warms the process-local cache.
2. Daemon startup (`assistant daemon`) — one `refresh()` over the
   persona's health-declaring entries before the scheduler starts, so
   the first scheduled runs skip a known-dead local node
   (error-swallowed; zero probes when no entry declares `health:`).
3. Programmatic `await monitor.refresh(refs)` for future consumers
   (e.g. a periodic P7 job).

Interactive CLI/serve paths deliberately do not pre-warm: their first
resolution sees UNKNOWN (eligible) and the P19 bind-time fallback
covers a dead node exactly as before this change.

## D4: `health:` config lives on the registry entry, parsed into `ModelRef.health`

Shape: `health: {path: /models, timeout: 2.0, ttl: 60}` — all keys
optional, defaults as shown (`GET <endpoint>/models` is the natural
OpenAI-compatible liveness probe; vLLM, Ollama's OpenAI facade, and
NIM all serve it). Validation at persona load: unknown keys rejected;
`timeout`/`ttl` must be positive numbers; `path` must start with `/`;
declaring `health:` on an entry without an `endpoint` is a
`ModelRegistryError` (there is nothing to probe on a hosted-default
entry). The parsed `EndpointHealth` rides on `ModelRef` so the
monitor and CLI can operate on refs without carrying the registry.

## D5: Embeddings wiring point is `create_graphiti_client`, opt-in by explicit binding

The `embeddings` consumer activates **only** via an explicit
`bindings: {embeddings: <entry>}` — the reserved `default` binding
does not spill into embeddings, because `default` almost always names
a chat model and a wrong-model embedding call fails at runtime, not
at load. Resolution goes through the normal
`RegistryModelProvider.resolve(ModelRequest(consumer="embeddings"))`
(so health filtering and fallback chains apply) and the first chain
member with dialect `openai-compatible` and a non-empty endpoint is
adapted; the P19 raw `OpenAICompatibleClient` supplies the wire call,
credential resolution (persona-scoped provider), and the
`model_call` budget hook (persona guardrails resolved the same way
`CapabilityResolver._resolve_guardrails` does).

`RegistryEmbedder` subclasses graphiti-core's `EmbedderClient` ABC
(already a dependency — no new packages) and truncates vectors to
`EmbedderConfig().embedding_dim`, matching graphiti's own
`OpenAIEmbedder` behavior so index dimensions stay consistent.

**Degradation is privacy-preserving**: a declared binding that cannot
be honored (resolution error, wrong dialect, missing endpoint)
disables Graphiti for that persona — `create_graphiti_client` returns
`None` with a warning, and memory degrades to Postgres-only exactly
like the established Graphiti-down path. Falling back to graphiti's
default embedder would silently ship memory content to cloud OpenAI
against the persona's stated intent. No binding at all keeps the
default embedder (current behavior, unchanged).

`MemoryManager` itself is untouched — it consumes the Graphiti client
opaquely, so the wiring point is the factory, not the manager.

## D6: Catalog cache shape and merge semantics

`assistant models sync-catalog` writes
`<persona_dir>/.cache/models/catalog.json` (the P13 git-ignored
`.cache/` convention, next to `guardrails/spend.json`):

```json
{
  "synced_at": "<UTC ISO-8601>",
  "url": "https://openrouter.ai/api/v1/models",
  "models": {
    "<openrouter id>": {
      "pricing": {"prompt": "0.000003", "completion": "0.000015", ...},
      "context_length": 200000,
      "modalities": {"input": ["text"], "output": ["text"]}
    }
  }
}
```

`pricing` is stored verbatim (OpenRouter key names — the shape
`compute_cost` and the P13 budget ledger already consume);
`modalities` is normalized from OpenRouter's
`architecture.input_modalities`/`output_modalities` into the
template's `{input: [...], output: [...]}` shape. At persona load,
`apply_catalog_metadata` fills `pricing` / `context_length` /
`modalities` **only when the entry left them empty** and the entry's
`id` matches a catalog row — declared values always win, local
entries without catalog rows are untouched, and a missing or
malformed cache file is a silent no-op (offline-safe, load stays
deterministic). Sync is explicit-CLI-only; persona load never touches
the network.

Fetch posture mirrors http_tools D9: `follow_redirects=False`
(refused redirects are a sync error), 10 MiB streaming size cap, TLS
verification on, 10 s read / 5 s connect timeouts, and the API key
(credential ref `OPENROUTER_API_KEY`, optional — the endpoint is
public) resolves through the persona-scoped `CredentialProvider` and
is never logged.

## D7: CLI grammar

A `models` click group (mirroring the `persona` / `db` group
precedent): `assistant models sync-catalog -p <persona> [--url]` and
`assistant models check-health -p <persona>`. `check-health` exits 1
when any probed endpoint is unhealthy so it can gate scripts;
`sync-catalog` exits 1 on any fetch failure with the transport error
named (the no-network case).
