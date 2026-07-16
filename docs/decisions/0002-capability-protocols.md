# ADR-0002: Five pluggable capability protocols plus CapabilityResolver

## Status

ACCEPTED — decided in OpenSpec change `capability-protocols`
(`openspec/changes/archive/2026-04-20-capability-protocols/`),
archived 2026-04-20. Extended (not superseded) by the planned P24
`capability-protocols-v2` contracts phase.

## Date

2026-04-20

## Context

Before this change, critical agent capabilities were either hardcoded
into the Deep Agents harness (e.g., `memory_files: ["./AGENTS.md"]`)
or missing entirely. Upcoming phases — P2 `memory-architecture`, P3
`http-tools-layer`, P13 `security-hardening` — needed stable
interfaces to implement against, or they would ship standalone modules
requiring protocol wrapping later. Three approaches were considered in
the proposal: (A) full re-abstraction of LangChain-style types, (B)
thin policy protocols over SDK-native types, (C) no protocols at all.
A was rejected as a re-abstraction tax (we would test wrappers, not
capabilities); C was rejected because it defers integration cost to
P11 `harness-routing` and leaves host harnesses unaddressed.

## Decision

Adopt approach B: define five protocols in
`src/assistant/core/capabilities/`, plus a resolver:

- **`GuardrailProvider`** (`guardrails.py`) — permission checks,
  policy gates, human-in-the-loop decisions. Genuinely new; no SDK
  covers it well.
- **`SandboxProvider`** (`sandbox.py`) — execution isolation, resource
  boundaries, rollback.
- **`MemoryPolicy`** (`memory.py`) — a factory/resolver that returns
  the right SDK-native memory backend per persona+harness; not a
  re-abstraction of `BaseChatMessageHistory`.
- **`ToolPolicy`** (`tools.py`) — tool authorization per persona+role,
  discovery-source configuration, tool-level ACLs; wraps SDK-native
  tool types rather than replacing them.
- **`ContextProvider`** (`context.py`) — persona/role assembly and
  prompt composition, formalizing `compose_system_prompt()`.

`CapabilityResolver` (`resolver.py`) assembles the capability set for
a persona config and harness tier: SDK harnesses get concrete
providers instantiated from persona config; host harnesses get
host-provided memory/sandbox/guardrails (e.g., `_HostProvidedSandbox`)
with context always self-provided. Shared dataclasses live in
`types.py` (e.g., `ActionDecision`, whose `require_confirmation` field
at `types.py:42` awaits a consumer under P24 contract 6).

## Consequences

- P2 implemented `PostgresGraphitiMemoryPolicy` against `MemoryPolicy`;
  P3's HTTP tools became a `ToolPolicy` source; the delegation spawner
  (`src/assistant/delegation/spawner.py`) consults `GuardrailProvider`
  before spawning.
- Protocols reference `Any` for SDK-native return types (multiple SDKs
  are supported), trading some type safety at the boundary for zero
  wrapping tax.
- Guardrail and sandbox providers shipped as allow-all/passthrough
  stubs (architecture-review finding H6); real implementations are
  sequenced into P13 and P22.
- The slot architecture was externally validated by AWS Bedrock
  AgentCore's near-1:1 decomposition (see
  `docs/architecture-analysis/2026-07-16-protocol-standards.md` §B);
  P24 adds `ModelProvider` as slot #6 (ADR-0005) rather than
  reopening the design.
