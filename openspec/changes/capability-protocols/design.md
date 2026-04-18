# Design — capability-protocols

## Context

The P1 vertical slice established seven capabilities (persona-registry,
role-registry, prompt-composition, harness-adapter, extension-registry,
delegation-spawner, cli-interface) with a single concrete harness
(Deep Agents). The architecture assumes one harness type — SDK-based,
where our code owns the agent loop.

In practice, the project uses two fundamentally different integration
patterns: SDK harnesses (Deep Agents, future ADK/Claude SDK/OpenAI SDK)
where we build the agent loop, and host harnesses (Claude Code, Codex)
where we're a payload inside someone else's loop. The current codebase
already functions as a host-harness integration (CLAUDE.md, skills/,
MCP servers) but this is manually maintained and disconnected from the
persona/role system.

This change introduces the architectural seams that P2 (memory), P3
(tools), P11 (harness-routing), P13 (security-hardening), and P16
(CLI harness integrations) will build against.

## Architectural Seams Exercised

| Seam | Interface exercised | Later proposal |
|------|---------------------|----------------|
| guardrail-provider | `GuardrailProvider.check_action(action) → Decision` | P13 (credential scoping) |
| sandbox-provider | `SandboxProvider.create_context() → ExecutionContext` | future (container isolation) |
| memory-policy | `MemoryPolicy.resolve(persona, harness) → MemoryConfig` | P2 (Postgres/Graphiti) |
| tool-policy | `ToolPolicy.authorized_tools(persona, role) → list[Any]` | P3 (HTTP discovery) |
| capability-resolver | `CapabilityResolver.resolve(persona, harness) → CapabilitySet` | P11 (auto-routing) |
| harness-adapter (sdk) | `SdkHarnessAdapter.create_agent(capabilities)` | P5 (MS Agent Framework) |
| harness-adapter (host) | `HostHarnessAdapter.export_context()` | P16 (Codex/Gemini) |

## Key Decisions

### D1: Policy protocols, not capability re-abstractions

**Why**: LangChain already provides `BaseTool`,
`BaseChatMessageHistory`, `BaseCallbackHandler`. Defining parallel
abstractions would create a wrapping tax without adding value. Instead,
`MemoryPolicy` and `ToolPolicy` are *configuration/factory* protocols
that resolve which SDK-native components to use for a given
persona+harness combination.

**Trade-off**: Protocol return types include `Any` for SDK-native
objects, reducing static type safety at protocol boundaries. Accepted
because the concrete harness implementations are strongly typed
internally; the protocol boundary is a routing seam, not a type-safety
boundary.

### D2: `GuardrailProvider` and `SandboxProvider` are genuinely new protocols

**Why**: No SDK provides application-level guardrails (persona-scoped
permission checks, coordination server policy gates) or
application-level sandboxing (worktree isolation, resource boundaries).
These are the two protocols where we define the abstraction, not just
the routing.

**Trade-off**: These protocols will initially ship with stub/passthrough
implementations. Concrete implementations arrive in P13
(security-hardening) and when execution isolation is needed. The stubs
are useful because they establish the call sites in
`DelegationSpawner.delegate()` and `SdkHarnessAdapter.create_agent()`
where real enforcement will later plug in.

### D3: Two-tier harness split (SDK vs Host), not three-tier

**Why**: Vendor agent platforms (VertexAI, AgentCore, Azure Foundry) are
architecturally identical to raw API/SDK harnesses — you write the agent
loop using their SDK, deploy locally or to their cloud. The
"managed cloud" aspect is a deployment concern (P18), not a harness
architecture concern. Two tiers (SDK owns loop vs. host owns loop)
capture the real structural difference.

**Trade-off**: A vendor SDK harness (e.g., ADK on Vertex) configures
memory/tools differently than a local Deep Agents harness, but this
difference is handled by `CapabilityResolver` returning different
configurations, not by a separate harness tier.

### D4: Host harness exports generated artifacts, not runtime objects

**Why**: When Claude Code is the host, there's no Python runtime to
inject objects into. The integration surface is files: CLAUDE.md
sections, `.claude/skills/`, MCP server configs. `HostHarnessAdapter`
generates these artifacts from persona+role config so they stay in sync
with the same source of truth as SDK harnesses.

**Trade-off**: Generated artifacts may drift from manually maintained
ones. Mitigated by making `assistant export` the canonical source and
documenting that manual edits to generated sections will be overwritten.
A future hook could auto-regenerate on persona config changes.

### D5: `CapabilitySet` is a plain dataclass, not a DI container

**Why**: The resolver returns a `CapabilitySet` holding resolved
capability instances. Using a DI container (e.g., `dependency-injector`)
would add a framework dependency for what is a simple struct of five
fields. The resolver is the factory; the set is the product.

**Trade-off**: Adding a sixth capability later requires updating the
dataclass. Acceptable because capability additions are infrequent and
should be deliberate (they represent architectural decisions, not
plug-in slots).

### D6: `ContextProvider` formalizes `compose_system_prompt()` without replacing it

**Why**: `compose_system_prompt()` is already harness-agnostic and
well-tested. `ContextProvider` wraps it as a protocol so both SDK and
host harnesses consume context through the same interface, but the
implementation delegates to the existing function.

**Trade-off**: Slight indirection. Justified because host harnesses need
context in a different format (Markdown sections for CLAUDE.md vs. a
single prompt string for SDK agents), and the protocol can dispatch to
the right formatter.

### D7: Stub `GuardrailProvider` defaults to `allow_all`

**Why**: P1.8 establishes call sites and protocols, not enforcement.
The stub `AllowAllGuardrails` permits every action, making it
behaviorally equivalent to the current system (no guardrails). P13
replaces this with real enforcement.

**Trade-off**: Until P13 lands, guardrail checks are no-ops. This is
explicitly the current state — we're adding the *seam*, not the
*enforcement*. The delegation spawner's existing role ACL checks remain
as the only active guard.

### D8: Directory restructure uses `sdk/` and `host/` subdirectories

**Why**: Flat `harnesses/` with `deep_agents.py`, `ms_agent_fw.py`,
`claude_code.py`, `codex.py` would mix two fundamentally different
adapter patterns in one namespace. The `sdk/` vs `host/` split makes
the architectural distinction visible in the file tree.

**Trade-off**: Breaking change to import paths. Mitigated by updating
all internal references in the same change and re-exporting from
`harnesses/__init__.py` for one release cycle (removed in the next
phase that touches harnesses).

### D9: CLI `export` is a subcommand, not a flag

**Why**: `--export` as a flag on the existing `main` command would
complicate the Click flow (mutually exclusive with REPL mode, different
required options). A `click.Group` with `run` (default, current REPL)
and `export` subcommands cleanly separates the two modes.

**Trade-off**: Changes the CLI invocation pattern. `assistant -p
personal` (current) becomes `assistant run -p personal`.
`assistant export -p personal --harness claude_code` is new. Mitigated
by making `run` the default group command so bare `assistant -p
personal` still works.

## Testing Strategy

- **Protocol conformance**: each capability protocol gets a
  `test_capabilities.py` suite asserting that stub implementations
  satisfy the protocol contract (runtime-checkable where possible).
- **Resolver**: `test_capability_resolver.py` asserts correct capability
  selection for SDK vs. host harness types per persona config.
- **Harness restructure**: existing `test_harnesses.py` updated for new
  import paths; no behavioral changes to Deep Agents tests.
- **CLI export**: `test_cli.py` gains export-mode tests using
  `CliRunner`.
- **Delegation guardrails**: `test_delegation.py` gains scenarios for
  `GuardrailProvider` consultation (stub allows all, so behavior
  unchanged but call site verified).
- **No LLM integration tests** in this phase — protocols are tested via
  stubs and fakes.

## Deferred Until Later Proposals

- Concrete `MemoryPolicy` for Postgres/Graphiti → P2
- Concrete `ToolPolicy` for HTTP tool discovery → P3
- Concrete `GuardrailProvider` for credential scoping → P13
- Dynamic harness selection logic → P11
- Codex/Gemini host harness adapters → P16
- Container-based `SandboxProvider` → future phase

## Open Questions

None blocking. The protocol shapes are informed by the capabilities
that P2/P3/P13 need; if those phases discover interface gaps, the
protocols can be extended (they're Python Protocols, not ABCs, so
adding optional methods is non-breaking).
