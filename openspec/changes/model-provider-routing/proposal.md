# model-provider-routing — Provider-Agnostic Model Layer + Capability Routing (P19)

## Why

Model access is lopsided and string-typed: DeepAgents calls LangChain
`init_chat_model` on a raw persona config string, the MSAF harness
constructs an env-var-driven `OpenAIChatClient`, and direct calls
(embeddings, summarization) have no client at all. The heterogeneous
fleet targeted by roadmap v3 (subscription seats, metered cloud,
local GX10 inference) needs capability-based routing with ordered
fallback chains, per-persona credential resolution, budget gating,
and cost attribution — without introducing a second
provider-abstraction library (ADR-0005: one model seam, not two).

The contracts already exist: capability-protocols-v2 (P24, archived
2026-07-16) specced `ModelRef` / `ModelProvider` / per-consumer
bindings (`openspec/specs/model-provider/spec.md`), the
`CredentialProvider` seam (`openspec/specs/credential-provider/spec.md`),
and `CapabilitySet` slot #6 (`openspec/specs/capability-resolver/spec.md`).
This change implements them.

## What Changes

- **Implement the `model-provider` capability** in
  `src/assistant/core/capabilities/models.py`: `ModelRef` (5-dialect
  closed vocabulary, credential ref, capability tags,
  OpenRouter-mirrored pricing/context/modalities), `ModelRequest`,
  runtime-checkable `ModelProvider` protocol, `StaticModelProvider`
  (persona per-harness `model` string → single-entry chain),
  `HostProvidedModelProvider`, and `RegistryModelProvider` (persona
  `models:` registry with tag filtering + ordered fallback chains).
- **Implement the `credential-provider` capability** in
  `src/assistant/core/capabilities/credentials.py`:
  `CredentialProvider` protocol + `EnvCredentialProvider` preserving
  the exact `_env()` semantics.
- **Per-consumer bindings** in
  `src/assistant/core/capabilities/model_bindings.py`: LangChain
  `init_chat_model` (DeepAgents), `agent-framework` `OpenAIChatClient`
  (MSAF, `openai-compatible` refs only), and a raw
  httpx-based OpenAI-compatible client (chat + embeddings) for direct
  calls. All bindings resolve `credential_ref` via `CredentialProvider`
  and gate dispatch via
  `GuardrailProvider.check_action(action_type="model_call")`.
- **Resolver slot #6 wiring**: `CapabilitySet.models`,
  `model_factory` override, host → `HostProvidedModelProvider`,
  sdk → `RegistryModelProvider` when the persona declares `models:`,
  else `StaticModelProvider`.
- **Persona registry validation**: `models:` parsed + validated at
  persona load (unknown dialect / out-of-vocabulary tag / dangling
  fallback fail with an actionable error); commented example in
  `personas/_template/persona.yaml`.
- **Harness integration**: both SDK harnesses consume
  `capabilities.models` + binding instead of raw config strings;
  persona-configured behavior is preserved via `StaticModelProvider`.
- **Cost attribution**: `@traced_harness` spans carry the resolved
  ref's name, dialect, and a `cost_usd` computed from
  OpenRouter-shaped pricing × reported token counts (omitted, never
  guessed, when pricing is absent).
- **Spec deltas (this change)**: a `model_id` wire-identifier
  refinement on `ModelRef`, deny-safe handling of
  `require_confirmation` until the approval interrupt flow lands, and
  the capability-resolver registry-selection refinement replacing the
  "StaticModelProvider until P19" placeholder scenario.

## Out of Scope

- OpenRouter `/models` catalog **sync** tooling and health-checked
  local GX10 registry entries — P20 `local-inference-node`.
- Non-allow-all budget guardrails — P13 `security-hardening` (the
  hook is wired; the default `AllowAllGuardrails` preserves behavior).
- Harness routing (`--harness auto`) — P11 consumes P19's vocabulary.
- The approval interrupt/resume flow for
  `require_confirmation=True` decisions — rides on durable sessions
  (capability-protocols-v2 follow-up); until then the binding denies.
- MSAF bindings for non-`openai-compatible` dialects — no connector
  packages exist for agent-framework 1.10.x.

## Impact

- Affected specs: `model-provider` (ADDED refinements),
  `capability-resolver` (MODIFIED requirement).
- Affected code: `src/assistant/core/capabilities/{models,credentials,
  model_bindings,types,resolver}.py`, `src/assistant/core/persona.py`,
  `src/assistant/harnesses/sdk/{deep_agents,ms_agent_fw}.py`,
  `src/assistant/telemetry/decorators.py`,
  `personas/_template/persona.yaml`, tests.
- No new dependencies (langchain provides `init_chat_model`; the raw
  binding uses the already-present `httpx`).
