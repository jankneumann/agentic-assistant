# Proposal: capability-protocols

## Why

The current `HarnessAdapter` assumes it owns the agent loop
(`create_agent` → `invoke` → `spawn_sub_agent`). This works for
SDK-based harnesses (Deep Agents, ADK, Claude Agent SDK) but is
structurally wrong for host harnesses (Claude Code, Codex) where the
host owns the loop and our code is the payload. Meanwhile, critical
agent capabilities — memory, guardrails, sandboxing, tool authorization
— are either hardcoded into the Deep Agents harness (e.g.,
`memory_files: ["./AGENTS.md"]`) or missing entirely, with no protocol
for subsequent phases (P2 memory-architecture, P3 http-tools-layer, P13
security-hardening) to implement against.

Defining capability protocols now — before P2/P3/P13 — means those
phases build to interfaces from day one rather than building standalone
modules that need protocol wrapping later.

## What Changes

### 1. Capability protocols

Introduce five protocol definitions in `src/assistant/core/capabilities/`:

- **`GuardrailProvider`** — permission checks, policy gates,
  human-in-the-loop decisions. Genuinely new; no SDK provides this well.
  Wraps the coordination server's `check_policy` / `check_guardrails`
  for SDK harnesses; host harnesses declare risk levels and let the host
  enforce.
- **`SandboxProvider`** — execution isolation, resource boundaries,
  rollback. Genuinely new; wraps worktree/container/host-provided
  sandboxes.
- **`MemoryPolicy`** — configures and returns the right SDK memory
  backend for a given persona+harness. Not a re-abstraction of
  `BaseChatMessageHistory`; a factory/resolver over SDK-native types.
  Replaces the hardcoded `memory_files` pattern.
- **`ToolPolicy`** — tool authorization per persona+role, discovery
  source configuration, tool-level ACLs. Wraps SDK-native tool types
  (`BaseTool`, `@tool`); does not replace them.
- **`ContextProvider`** — persona/role assembly, prompt composition,
  session state. Formalizes what `compose_system_prompt()` already does
  as a protocol that both harness types consume.

### 2. Two-tier harness split

Refactor `src/assistant/harnesses/` into two categories:

- **`sdk/`** — SDK-based harnesses that own the agent loop. Current
  `DeepAgentsHarness` moves here. Future ADK, Claude Agent SDK, OpenAI
  Agents SDK, Strands harnesses follow the same pattern.
  `SdkHarnessAdapter` extends `HarnessAdapter` with capability
  injection.
- **`host/`** — host harnesses where the host owns the loop. Our code
  exports configuration artifacts (CLAUDE.md sections, MCP server
  configs, skill definitions, guardrail declarations). New
  `HostHarnessAdapter` with `export_*` methods replaces the current
  manually-maintained integration files.

### 3. Capability resolver

`CapabilityResolver` in `src/assistant/core/capabilities/resolver.py`
that, given a persona config and harness type, returns the appropriate
capability implementations:

- SDK harness: instantiates concrete providers from persona config
- Host harness: marks memory/sandbox/guardrails as "host-provided",
  context always "self-provided"

### 4. CLI export mode

Add `assistant export --harness claude_code --persona personal` that
generates host-harness integration artifacts instead of starting the
REPL. The interactive REPL path remains unchanged.

### 5. **BREAKING** — Harness directory restructure

Move `deep_agents.py` → `sdk/deep_agents.py`,
`ms_agent_fw.py` → `sdk/ms_agent_fw.py`. Update factory imports.

## Approaches Considered

### Approach A: Full re-abstraction — define our own Memory, Tool, Guardrail abstractions parallel to LangChain — Effort: L

**Description**: Create complete protocol hierarchies for every
capability, independent of any SDK. Each SDK harness wraps its native
types behind our protocols.

- **Pros**: Maximum portability; no SDK coupling; clean mental model.
- **Cons**: Duplicates mature SDK abstractions (LangChain `BaseTool`,
  `BaseChatMessageHistory`); every SDK integration pays a wrapping tax;
  maintenance burden grows with each new SDK; the abstractions would be
  tested only via the wrapping layer, not directly.

### Approach B (Recommended): Policy protocols over SDK-native types — Effort: M

**Description**: Define thin *policy* protocols (`MemoryPolicy`,
`ToolPolicy`) that configure and return SDK-native types, plus genuinely
new protocols (`GuardrailProvider`, `SandboxProvider`) where no SDK
coverage exists. Reuse SDK types directly for tool definitions, memory
backends, observability callbacks.

- **Pros**: No re-abstraction tax; each SDK's strengths used directly;
  protocols focus on application-level routing (which memory backend for
  this persona?) not SDK-level mechanics; `GuardrailProvider` and
  `SandboxProvider` fill real gaps.
- **Cons**: Protocols reference `Any` for SDK-native return types (since
  we support multiple SDKs); slightly looser type safety at protocol
  boundaries.

### Approach C: No protocols, just configure each harness directly — Effort: S

**Description**: Each harness implementation handles its own memory,
tools, guardrails inline. No shared abstractions.

- **Pros**: Simplest; no premature abstraction.
- **Cons**: P2 (memory) and P3 (tools) would build standalone modules
  that later need protocol wrapping when P11 (harness-routing) lands;
  host-harness support has no integration point; guardrails are
  per-harness rather than per-persona.

### Selected Approach: **B — Policy protocols over SDK-native types**

Chosen because it avoids the re-abstraction trap of Approach A while
giving P2/P3/P13 stable interfaces to implement against. Unselected:

- **A** rejected: wrapping mature SDK types adds indirection without
  value; we'd test wrappers, not capabilities.
- **C** rejected: defers the integration cost to P11 when it's harder
  to change; leaves host harnesses unaddressed.

## Capabilities

### New Capabilities

- `guardrail-provider`: Protocol for permission checks, policy gates,
  and human-in-the-loop decisions. SDK harnesses implement via
  coordination server; host harnesses declare risk levels.
- `sandbox-provider`: Protocol for execution isolation, resource
  boundaries, and rollback. SDK harnesses implement via
  worktree/container; host harnesses delegate to host sandbox.
- `memory-policy`: Factory/resolver that configures the right memory
  backend for a given persona+harness combination. Returns SDK-native
  memory types.
- `tool-policy`: Tool authorization per persona+role, discovery source
  configuration, tool-level ACLs. Wraps SDK-native tool types.
- `capability-resolver`: Given a persona config and harness type,
  assembles the full capability set with appropriate implementations.

### Modified Capabilities

- `harness-adapter`: Split into `SdkHarnessAdapter` (owns loop, receives
  capabilities) and `HostHarnessAdapter` (exports config, host owns
  loop). Factory updated for two-tier routing. **BREAKING**: directory
  restructure.
- `extension-registry`: Extensions become one source that `ToolPolicy`
  manages alongside HTTP tools and MCP servers.
- `delegation-spawner`: Spawner consults `GuardrailProvider` for
  delegation policy in addition to existing role ACL checks.
- `cli-interface`: Gains `export` subcommand for host-harness artifact
  generation.

## Impact

- **Affected code**: `src/assistant/harnesses/` (restructured),
  `src/assistant/core/capabilities/` (new), `src/assistant/cli.py`
  (export mode), `src/assistant/delegation/spawner.py` (guardrail
  integration), `tests/` (new capability tests, updated harness tests).
- **Affected specs**: `harness-adapter` (modified), `extension-registry`
  (modified), `delegation-spawner` (modified), `cli-interface`
  (modified).
- **Dependencies**: None — can proceed immediately (P1.7
  `bootstrap-fixes` is independent of this work).
- **Breaking changes**: harness module paths change
  (`harnesses/deep_agents` → `harnesses/sdk/deep_agents`); existing
  tests and imports need updating.

## Out of Scope (deferred to later phases)

- Concrete `MemoryPolicy` implementations (Postgres, Graphiti) → **P2
  memory-architecture**
- HTTP tool discovery as a `ToolPolicy` source → **P3
  http-tools-layer**
- Credential scoping as a `GuardrailProvider` implementation → **P13
  security-hardening**
- Dynamic harness routing (`--harness auto`) → **P11 harness-routing**
- Real host-harness export for Codex → **P16 cli-harness-integrations**
- Concrete `SandboxProvider` implementations beyond stub → deferred
  until a phase needs execution isolation
