# capability-protocols-v2 — Tasks

Contracts-only change: all tasks are spec-authoring tasks. No
implementation code ships in this change.

## 1. Authoring

- [x] 1.1 proposal.md — Why (seven seam gaps, contracts before
  parallel roadmap execution), What Changes (seven deltas), Impact
  (specs touched; no code)
- [x] 1.2 design.md — one section per contract (C1–C7) recording the
  decision shape and its provenance (roadmap P24 row + principles 5/7,
  protocol-standards doc, ADR-0005, ADR-0006, current
  `capabilities/` + `harnesses/base.py` code)
- [x] 1.3 specs/model-provider/spec.md — ADDED: ModelRef, capability
  tag vocabulary, persona model registry, ModelProvider protocol
  (ordered fallback resolution), per-consumer bindings, model-call
  budget hook, cost attribution, default providers
- [x] 1.4 specs/tool-spec/spec.md — ADDED: MCP-shaped ToolSpec, all
  sources compile to it, per-harness adapters, deprecation path for
  `as_langchain_tools()` / `as_ms_agent_tools()`
- [x] 1.5 specs/sandbox-provider/spec.md — ADDED: SandboxConfig v2
  three planes + named enforcement seam; MODIFIED: PassthroughSandbox
  stub accepts v2 without enforcement, stays default
- [x] 1.6 specs/guardrail-provider/spec.md — ADDED: ApprovalRequest
  type (MCP-elicitation mirror), approval interrupt/resume over the
  durable-session checkpoint with audit trail,
  escalation-with-justification
- [x] 1.7 specs/harness-adapter/spec.md — MODIFIED: Deep Agents
  harness + SDK harness adapter `create_agent(tools)` cleanup
  (ToolPolicy sole aggregator); ADDED: durable session persistence
  (LangGraph checkpointer, Postgres impl) + session registry
- [x] 1.8 specs/capability-resolver/spec.md — MODIFIED: CapabilitySet
  slot #6, resolver assembly + `model_factory` override,
  host-provided model slot, traced aggregation collapses to the
  single ToolPolicy site
- [x] 1.9 specs/credential-provider/spec.md — ADDED: CredentialProvider
  protocol, EnvCredentialProvider default (`_env()` semantics),
  all-secret-reads-through-the-seam; inbound/outbound noted as P25
  scope
- [x] 1.10 specs/memory-policy/spec.md — MODIFIED: async
  `get_recent_snippets` at the protocol level (owner review verdict
  C8, 2026-07-16); requirement text kept identical to the open P21
  memory-policy delta so archive order (P24 then P21) yields the
  same spec

## 2. Validation

- [x] 2.1 `openspec validate capability-protocols-v2 --strict` passes

## 3. Review

- [x] 3.1 Owner review + archive (`/openspec-archive-change (approved 2026-07-16, verdicts 1-10)
  capability-protocols-v2`; update roadmap P24 status to archived)
