# capability-protocols-v2 — Contracts-Only Seam Codification (P24)

## Why

Roadmap v3 queues several phases for parallel execution (P13
`security-hardening`, P19 `model-provider-routing`, P22
`meta-harness-compat`, plus P6/P7 daemon surfaces). They all build
against the capability protocols established in P1.8 — and the
2026-07-07 architecture review plus the 2026-07-16 ecosystem brief
(`docs/architecture-analysis/2026-07-16-protocol-standards.md`)
identified seven seam gaps in those contracts that would otherwise be
re-invented divergently inside each parallel work package:

1. **No model seam.** Model access is lopsided: LangChain
   `init_chat_model` in DeepAgents only, `agent-framework` chat clients
   in MSAF, nothing for direct calls (embeddings, summarization). ADR
   0005 decided the shape (one `ModelProvider` seam → harness-neutral
   `ModelRef` → thin per-consumer bindings); no contract exists yet.
2. **No single tool representation.** Extensions carry per-harness
   methods (`as_langchain_tools()`, `as_ms_agent_tools()`); OpenAPI
   tools are wrapped separately. AgentCore's Gateway lesson: one
   compiler, one output type — an MCP-shaped `ToolSpec`.
3. **SandboxConfig is a stub** (`isolation_type` + metadata dict). It
   cannot express the filesystem/network/credential planes that P22's
   real sandbox provider and P13's posture need, and no enforcement
   seam is named.
4. **`create_agent` re-aggregates tools.** The DeepAgents harness
   re-wraps extension tools that `ToolPolicy.authorized_tools` already
   aggregated — two aggregation sites that can drift, and no place for
   a future tool-search/ranking stage to slot in.
5. **Sessions are not durable or multiplexable.** `web/app.py` builds
   one global harness at startup; the DeepAgents checkpointer is
   `InMemorySaver`. The P7 daemon and P6 A2A server cannot multiplex
   users/tasks without a durable-session contract and a session
   registry.
6. **`ActionDecision.require_confirmation` is consumed by nothing**
   (`capabilities/types.py:42`). There is no interrupt/resume
   machinery, so no guardrail can actually ask a human.
7. **Credentials are ambient env vars** read through scattered
   `_env()` helpers. P25's OpenBao backend needs a single lookup seam
   to swap into without touching call sites.

This change is a **contracts-only pre-phase**: spec deltas that the
P13/P19/P22 (and P6/P7) implementations will be reviewed against. No
implementation code ships here.

## What Changes

- **NEW capability `model-provider`** — `ModelProvider` protocol as
  `CapabilitySet` slot #6: harness-neutral `ModelRef` (name, wire
  dialect, endpoint, credential ref, capability tags, pricing fields
  mirroring the OpenRouter `/models` schema), persona-level model
  registry, requirements→`ModelRef` resolution with ordered fallback,
  per-consumer bindings (LangChain `init_chat_model`, MSAF chat
  clients, raw OpenAI-compatible client incl. embeddings), budget hook
  via `GuardrailProvider.check_action(ActionRequest(
  action_type="model_call"))`, cost attribution through telemetry.
- **NEW capability `tool-spec`** — harness-neutral MCP-shaped
  `ToolSpec` (name, description, JSON-Schema input, async callable) as
  the single internal tool representation; per-harness adapters render
  it native; OpenAPI-derived and extension tools compile into it;
  deprecation path for `Extension.as_langchain_tools()` /
  `as_ms_agent_tools()`.
- **NEW capability `credential-provider`** — single lookup seam for
  secrets/API keys; default implementation is the existing `_env()`
  indirection; designed so the OpenBao backend (P25) swaps in without
  touching call sites. Inbound-vs-outbound credential modeling is
  noted as P25 scope.
- **MODIFIED `sandbox-provider`** — `SandboxConfig` v2 with three
  planes: filesystem (named levels `read-only` / `workspace-write` /
  `full-access` + mounts), network (deny-by-default egress with
  allow-list + proxy), credentials (explicit secret visibility set);
  named enforcement seam at tool invocation and the extension
  subprocess boundary; `PassthroughSandbox` remains the default
  implementation.
- **MODIFIED `guardrail-provider`** — approval interrupt/resume: a
  `require_confirmation` decision suspends the run via the
  durable-session checkpoint, emits a channel-agnostic
  `ApprovalRequest` (shape mirroring MCP elicitation, risk-tiered via
  `RiskLevel`), and resumes with the recorded decision in an audit
  trail; escalation-with-justification supported.
- **MODIFIED `harness-adapter`** — (a) `create_agent(tools)` signature
  cleanup: `ToolPolicy` is the sole tool aggregator; harnesses MUST
  NOT re-aggregate or re-wrap extension tools; (b) durable-session
  contract: SDK harnesses expose checkpointer-backed session
  persistence (LangGraph checkpointer interface with a Postgres
  implementation for DeepAgents) and a session registry
  (create/lookup/expire by `thread_id`) so the daemon and A2A server
  can multiplex.
- **MODIFIED `memory-policy`** (added post-review — owner review
  verdict C8, 2026-07-16) — `MemoryPolicy.get_recent_snippets`
  becomes `async` at the protocol level so P19+ consumers never build
  on a sync-to-async bridge; async consumers await it directly, sync
  callers (host export / CLI export) bridge at their own edge. The
  open P21 `memory-retrieval-activation` implementation was updated
  to match in the same session (its memory-policy delta carries the
  identical final requirement text).
- **MODIFIED `capability-resolver`** — resolver assembles slot #6
  (`ModelProvider`) with the same factory-override pattern; host
  harnesses get a host-provided model slot; the traced-aggregation
  requirement collapses to the single ToolPolicy aggregation site.

## Impact

- **Specs touched:** `model-provider` (new), `tool-spec` (new),
  `credential-provider` (new), `sandbox-provider`,
  `guardrail-provider`, `harness-adapter`, `capability-resolver`,
  `memory-policy` (post-review, verdict C8).
- **Code:** none shipped under this change-id — the verdict-C8 async
  retrieval implementation rides under the open P21
  `memory-retrieval-activation` change. All other deltas are
  contracts that downstream phases implement — P19 (`model-provider`,
  budget hook, cost attribution), P13 (`credential-provider` env
  scoping, first real guardrails), P22 (sandbox planes enforcement),
  P6/P7 (session registry consumers), P25 (OpenBao
  `CredentialProvider` backend).
- **Migration:** requirements marked as deprecation paths
  (`as_*_tools()`, tool re-aggregation in `create_agent`) take effect
  when the consuming phases land; nothing breaks at archive time
  because no code changes here.
- **Standards mapping:** every new shape follows
  `docs/architecture-analysis/2026-07-16-protocol-standards.md` —
  `ToolSpec` = MCP tool schema shape, `ApprovalRequest` = MCP
  elicitation mirror, sandbox FS levels = Codex policy vocabulary,
  model catalog = OpenRouter `/models` mirror, sessions = LangGraph
  checkpointer interface.
