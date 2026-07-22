# ADR-0005: One model seam — ModelProvider → ModelRef → per-consumer bindings

## Status

ACCEPTED — decided 2026-07-16 in OpenSpec change
`roadmap-v3-heterogeneous-fleet`
(`openspec/changes/archive/2026-07-16-roadmap-v3-heterogeneous-fleet/`);
recorded as roadmap guiding principle 5 in `openspec/roadmap.md`.
Implementation pending: contract in P24 `capability-protocols-v2`
(ModelProvider as capability slot #6), implementation in P19
`model-provider-routing`.

## Date

2026-07-16

## Context

The heterogeneous fleet targeted by roadmap v3 (per
`docs/architecture-analysis/2026-07-07-architecture-review.md`) spans
subscription seats, metered cloud providers (OpenRouter, hyperscaler
model gardens), and local inference on the GX10 node. Today model
access is partial and lopsided: DeepAgents uses LangChain
`init_chat_model`, the MSAF harness uses `agent-framework` chat
clients that cannot consume LangChain model objects, and direct calls
(embeddings, summarization) need no harness at all. The temptation is
a second provider-abstraction library (e.g., LiteLLM) — but per the
protocol-standards analysis
(`docs/architecture-analysis/2026-07-16-protocol-standards.md`, matrix
row "Model calling (wire)" and consequence D.9), the wire protocols
are already converged standards (OpenAI-compatible Chat Completions,
Anthropic Messages, Gemini generateContent, Bedrock/Vertex), and
`init_chat_model` is a *binding*, not the seam.

## Decision

There is exactly **one model seam, not two**: the `ModelProvider`
protocol. It resolves capability requirements to a harness-neutral
**`ModelRef`** — wire dialect, endpoint, credential ref, capability
tags (`fast`, `cheap`, `long-context`, `local-only`,
`private-data-ok`, ...), and pricing — and thin **per-consumer
bindings** adapt the `ModelRef`:

- LangChain `init_chat_model` for LangChain-native harnesses
  (DeepAgents);
- `agent-framework` chat clients for the MSAF harness;
- a raw OpenAI-compatible client for direct calls (embeddings,
  summarization) — this dialect alone covers OpenRouter and all local
  backends (vLLM, Ollama, NIM on the GX10).

No second provider-abstraction library is introduced unless a binding
proves insufficient; if that happens it is recorded as a superseding
ADR when P19 lands. Model *metadata* has no converged standard, so the
P19 catalog mirrors the OpenRouter `/models` schema (id, pricing,
context length, modalities) as a migration-shaped placeholder.

## Consequences

- Both SDK harnesses will consume the router instead of raw model-id
  strings; per-persona API keys resolve via the P24 `CredentialProvider`
  seam, budgets via `GuardrailProvider`, cost attribution via existing
  telemetry spans (P4).
- Cloud catalog entries sync verbatim from OpenRouter; local GX10
  entries are hand-authored in the same shape (P20).
- Model routing (P19) is deliberately separated from harness routing
  (P11), which consumes P19's capability vocabulary.
- Until P24/P19 land, the asymmetry persists: `init_chat_model` in
  DeepAgents only, and no capability-based fallback chains.
