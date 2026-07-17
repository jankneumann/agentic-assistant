# GX10 Local Inference Node — Quickstart

How to make a local OpenAI-compatible endpoint (ASUS Ascent GX10 — or
any box running NIM, vLLM, or Ollama) a first-class citizen of a
persona's model registry (P20 `local-inference-node`). The assistant
never cares *which* server you run: dialect `openai-compatible` plus a
base URL fully describes the backend.

## 1. Serve a model (pick one)

All three expose the same two endpoints the assistant uses:
`GET /v1/models` (health probe) and `POST /v1/chat/completions` /
`POST /v1/embeddings` (inference).

**vLLM** (chat on :8000, embeddings on :8001):

```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct --host 0.0.0.0 --port 8000
vllm serve nvidia/NV-Embed-v2 --task embed --host 0.0.0.0 --port 8001
```

**Ollama** (single port; OpenAI facade under `/v1`):

```bash
ollama pull llama3.1:8b && ollama pull nomic-embed-text
# endpoint: http://<host>:11434/v1
```

**NIM** (DGX OS / containerized; one container per model):

```bash
docker run --gpus all -p 8000:8000 nvcr.io/nim/meta/llama-3.1-8b-instruct:latest
# embedding NIMs (e.g. nvidia/nv-embedqa-e5-v5) ship as separate containers
```

Verify from the machine that runs the assistant:

```bash
curl http://gx10.local:8000/v1/models
```

## 2. Declare the node in the persona registry

In the persona's private `persona.yaml` (schema documented in
`personas/_template/persona.yaml`):

```yaml
models:
  entries:
    sonnet:
      dialect: anthropic
      id: claude-sonnet-4-20250514
      credential_ref: ANTHROPIC_API_KEY
      tags: [coding, long-context]
      fallbacks: [gx10-chat]
    gx10-chat:
      dialect: openai-compatible
      id: llama-3.1-8b-instruct          # name the server reports in /v1/models
      endpoint: "http://gx10.local:8000/v1"
      tags: [fast, cheap, local-only, private-data-ok]
      health: {path: /models, timeout: 2.0, ttl: 60}
      fallbacks: [sonnet]                # cloud fallback for non-private work
    gx10-embed:
      dialect: openai-compatible
      id: nvidia/nv-embedqa-e5-v5
      endpoint: "http://gx10.local:8001/v1"
      tags: [cheap, local-only, private-data-ok]
      health: {path: /models}
  bindings:
    default: sonnet          # interactive tier stays on cloud
    scheduler: gx10-chat     # background jobs run local/cheap
    embeddings: gx10-embed   # Graphiti semantic memory embeds locally
```

Notes:

- `id` must match a model name from the server's `GET /v1/models`
  response (Ollama: the tag, e.g. `llama3.1:8b`).
- `credential_ref` is only needed if the server enforces API keys
  (`--api-key` in vLLM); the value lives in the persona's git-ignored
  `.env`.
- The `embeddings` binding must be **explicit** — the `default`
  binding never spills into embeddings. Without it, Graphiti keeps its
  default (cloud OpenAI) embedder.
- Local entries omit `pricing` — cost is then omitted from telemetry,
  never guessed.

## 3. Verify

```bash
# probe every health-declaring entry (exit 1 if any endpoint is down)
uv run assistant models check-health -p <persona>

# optional: pull OpenRouter pricing metadata for cloud entries
uv run assistant models sync-catalog -p <persona>

# run the daemon — it pre-warms health state and prints verdicts
uv run assistant daemon -p <persona>
```

## 4. What health checking does (and does not) do

- Resolution consults **cached** probe verdicts only — it never blocks
  on the network. States: no `health:` block → always eligible;
  never-probed or stale (older than `ttl`) → eligible (optimistic);
  fresh unhealthy verdict → skipped, fallback chain proceeds.
- **Privacy fails closed**: when a request requires `local-only` /
  `private-data-ok` and no healthy entry carries those tags,
  resolution raises instead of silently routing to cloud. The same
  applies to memory embeddings — an unhonorable `embeddings` binding
  disables Graphiti (Postgres-only memory) rather than falling back to
  the default cloud embedder.
- Pre-warm points: `assistant models check-health`, daemon startup.
  Interactive sessions start optimistic and rely on the P19 bind-time
  fallback walk if the node is down.

## Related

- Roadmap P23 `deployment-topology` owns the full home-lab story
  (systemd/compose service definitions, per-persona DBs on the node).
- Fleet rationale: `docs/architecture-analysis/2026-07-07-architecture-review.md` §1.
