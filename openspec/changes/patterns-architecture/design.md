# Design: patterns-architecture

> Planning-only. No production code changes. This document establishes
> architectural framing that downstream proposals (P1.7, P6, P11, P12,
> P16, P17) reference when they implement concrete capabilities.

---

## D1 — Four-Layer Model

The agentic-assistant architecture is organized into four layers. Each
layer has a distinct responsibility and a clear interface to the layers
above and below it.

### Layer 1 — Assistant Framework

**Responsibility**: shared infrastructure that every harness consumes.

Includes: persona system, role system, memory, tool registry, context
search, human communication channels (CLI, chat), extension lifecycle.

The framework owns the *definition* of patterns (Layer 3) but does not
own their *implementation* — that belongs to the harness or to the
transport layer.

### Layer 2 — Harness Runtime

**Responsibility**: execute an agent loop using the framework's shared
capabilities.

Each harness has its own native idioms:

| Harness | Native idiom | Status |
|---------|-------------|--------|
| Deep Agents (LangGraph) | Node-graph planning + tool-use via LangChain | Implemented (P1) |
| Claude Code | Built-in ReAct loop (Read/Edit/Bash/Grep tool cycle) | Future (P16) |
| Codex | OpenAI function-calling agent loop | Future (P16) |
| Google ADK | Multi-agent composition primitives (critic, planner, executor sub-agents) | Future (P16) |
| MS Agent Framework | Orchestration primitives (Semantic Kernel, planners) | Stubbed (P1); real in P5 |

A harness receives `PersonaConfig`, `RoleConfig`, tools, and extensions
from Layer 1 and produces an opaque agent that can be invoked. The
harness is free to use whatever internal architecture it needs (graph
nodes, ReAct loops, function calls, etc.) as long as it honors the
`HarnessAdapter` contract.

### Layer 3 — Patterns

**Responsibility**: cross-cutting abstractions that are defined at the
framework layer but implemented per-harness.

A pattern is a reusable behavioral capability — e.g., "consult a more
capable model when stuck" (advise), "delegate a sub-task to a
role-switched sub-agent" (delegate), "search accumulated memory for
relevant context" (memory-search).

Patterns have three defining characteristics:

1. **A contract**: what the pattern does, what inputs it takes, what
   outputs it produces. Defined by the framework.
2. **Per-harness implementations**: each harness declares how (or
   whether) it supports the pattern.
3. **Multiple implementation modes**: a harness may support a pattern
   natively, emulate it generically, delegate it via transport, or
   declare it unsupported.

### Layer 4 — Transport

**Responsibility**: cross-process communication between agents or
between an agent and an external service.

Three transport protocols are enumerated:

- **A2A** (Agent-to-Agent): for patterns where the remote endpoint is
  another agent that performs work and returns results. Used when the
  pattern is semantically "do something" (delegate, advise).
- **MCP** (Model Context Protocol): for patterns where the remote
  endpoint provides tools or context. Used when the pattern is
  semantically "provide something" (memory-search, tool discovery).
- **HTTP**: generic fallback for services that don't implement A2A or
  MCP natively.

Protocol selection mechanics (which transport to use for which pattern,
how to discover endpoints, authentication) are deferred to **P6
`a2a-server`** and **P17 `mcp-server-exposure`**.

---

## D2 — Capability

A **Capability** is a named identifier that represents a pattern a
harness may support. It is the unit of composition between roles (which
require capabilities) and harnesses (which provide them).

### Enumerated capabilities

P1.6 formalizes one capability and lists likely future candidates:

| Capability | Description | First consumer |
|-----------|-------------|---------------|
| **ADVISE** | Consult a more capable model on shared context; receive guidance, not delegation | P1.7 |
| DELEGATE *(future)* | Spawn a role-switched sub-agent with fresh context to perform work | P12 |
| MEMORY_SEARCH *(future)* | Query accumulated memory (Postgres, Graphiti) for relevant context | P2 |
| PLAN *(future)* | Decompose a goal into sub-tasks with dependency ordering | (unassigned) |
| REFLECT *(future)* | Self-assess progress against criteria and decide whether to continue, escalate, or stop | (unassigned) |

Only ADVISE is formalized here. Future capabilities are added by the
downstream proposals that implement them — each authors a delta spec to
`patterns-architecture` when it introduces a new Capability.

### Representation

P1.6 does **not** prescribe a concrete type (enum, string registry,
etc.). The representation is an implementation choice for the first
downstream proposal that needs it (P1.7). The spec requires only that:

- Each capability has a unique, stable identifier.
- New capabilities can be added without modifying existing code (open
  for extension).
- The set of known capabilities is discoverable at runtime.

---

## D3 — CapabilityInfo

A **CapabilityInfo** is the declaration a harness makes about a specific
capability. It answers: "does this harness support this capability, and
if so, how?"

### Fields

| Field | Description |
|-------|------------|
| **mode** | One of: `native`, `emulated`, `transport-mediated`, `not_supported`. |
| **cost_characteristic** | Qualitative: `cheap`, `moderate`, `expensive`. Informs routing and observability. |
| **notes** | Optional free-text. E.g., "2 API roundtrips; single-call not possible on this harness." |

### Implementation modes

- **Native**: the harness implements the pattern using its own
  primitives. Example: Deep Agents implements ADVISE by including the
  Anthropic advisor tool in the Messages API call. Cheapest, most
  context-preserving.
- **Emulated**: the framework provides a generic implementation that
  uses the harness's existing primitives (invoke, tool calls) to
  approximate the pattern. Example: MS Agent Framework emulates ADVISE
  by making a separate Opus API call with the transcript passed as
  context. Functionally equivalent; typically more expensive.
- **Transport-mediated**: the pattern runs in a separate agent or
  service, reached via A2A, MCP, or HTTP. The local harness acts as a
  client; the remote endpoint does the work. Example: a Claude Code
  session delegates to a Deep Agents service over A2A.
  Transport-mediated mode is enumerated here but its mechanics are
  deferred to P6/P17.
- **Not supported**: the harness cannot provide this capability in any
  mode. Roles requiring this capability cannot bind to this harness.

### Defaults

If a harness does not declare a CapabilityInfo for a capability, the
default is `not_supported`. Harnesses must opt in explicitly.

---

## D4 — Role Capability Requirements

A role declares which capabilities it needs via a
`required_capabilities` field.

Semantics:

- A role with `required_capabilities: [ADVISE]` can only be bound to a
  harness that declares ADVISE with a mode other than `not_supported`.
- A role with an empty or absent `required_capabilities` field can bind
  to any harness (backwards-compatible default).
- An optional `preferred_capability_modes` field lets a role express
  preference without hard constraint — e.g., "prefer native ADVISE, but
  accept emulated." Matching logic is deferred to P11.

---

## D5 — Factory Contract

The harness factory (currently `src/assistant/harnesses/factory.py`)
binds a role to a harness at runtime.

### Contract (defined here)

The factory SHALL bind a role to a harness only if the harness's
declared capabilities satisfy all entries in the role's
`required_capabilities`. If no configured harness satisfies the role, the
factory SHALL raise a clear error identifying the unmet capabilities.

### Not defined here

- **Matching algorithm** (preference order, tie-breaking, fallback
  chains): deferred to **P11 `harness-routing`**.
- **Per-task routing** (selecting different harnesses for different tasks
  within a single role): deferred to **P11**.
- **Cross-harness delegation** (a role running on one harness delegates
  a sub-task to a different harness): deferred to **P12
  `delegation-context`**.

---

## D6 — Anti-patterns

These are explicitly called out to prevent downstream proposals from
re-introducing known failure modes.

### AP1 — Transcript summarization before advisor call

**Wrong**: Compress or summarize the executor's transcript before passing
it to the advisor, to save tokens.

**Why it fails**: The advisor's quality depends on seeing the full
transcript — including tool results and error messages. Summarization
strips exactly the detail the advisor needs to diagnose "stuck" states.
The blog's quality numbers (Sonnet+Opus +2.7pp on SWE-bench Multilingual)
were measured on full-context advisor calls.

**Right**: Pass the full transcript. If budget is a concern, use the
advisor's `budget_tokens` config to cap the *response*, not the input.

### AP2 — Conflating advisor with delegation

**Wrong**: Implement ADVISE as a special case of DELEGATE (spawn a
sub-agent with the advisor model).

**Why it fails**: Delegation creates a fresh context (the sub-agent
doesn't see the parent's transcript). The advisor's value is
shared-context consultation — it reads the executor's full conversation
and returns guidance within the same conceptual session. Implementing
ADVISE via DELEGATE loses the shared context and with it the quality win.

**Right**: ADVISE and DELEGATE are separate capabilities with distinct
contracts. ADVISE shares context; DELEGATE forks it.

### AP3 — Fat interface growth

**Wrong**: Add each new pattern as a new abstract method on
`HarnessAdapter` (advise(), plan(), reflect(), checkpoint(), ...).

**Why it fails**: Every new method × every harness = a new
`raise NotImplementedError` stub. Harnesses that don't support a pattern
still have to implement the method. The interface grows linearly with
patterns; the stub count grows quadratically.

**Right**: Use the capability declaration model. Harnesses declare what
they support; roles declare what they need; the factory matches. No stubs.

---

## Appendix A — Worked Example: ADVISE as Capability

This appendix walks through the ADVISE capability to validate the
framing. No Python types or file paths are prescribed — this is a
conceptual narrative.

### Step 1 — Pattern definition (Layer 3)

The ADVISE pattern is defined at the framework layer:

- **Contract**: Given the executor's full transcript and a question
  from the executor, consult a more capable model and return textual
  guidance (plan, correction, or stop signal). The advisor reads the
  shared context; it does not fork a new context (cf. AP2).
- **Inputs**: transcript (conversation history including tool
  results), question (the executor's specific request for advice).
- **Outputs**: guidance text, model identity, token usage.

### Step 2 — Role declaration (Layer 1)

The `coder` role's configuration declares:

```yaml
required_capabilities:
  - ADVISE

advisor:
  model: claude-opus-4-6
  trigger: on_demand
  max_calls_per_task: 3
  budget_tokens: 1800

executor_model: anthropic:claude-sonnet-4-6
```

This tells the framework: "coder needs a harness that supports ADVISE."
The `advisor:` block provides pattern-specific configuration; the
`executor_model` enables the cost story (cheap executor + expensive
advisor).

### Step 3 — Harness declarations (Layer 2)

**Deep Agents** declares ADVISE as native:

```
Capability: ADVISE
Mode: native
Cost: cheap
Notes: Single API call with advisor_20260301 tool type + beta header.
       Full transcript shared in-request. ~400-700 token response.
```

The implementation uses the Anthropic Messages API directly (bypassing
LangChain for this specific call), including the `advisor_20260301` tool
in the tools array and the `anthropic-beta: advisor-tool-2026-03-01`
header.

**MS Agent Framework** declares ADVISE as emulated:

```
Capability: ADVISE
Mode: emulated
Cost: expensive
Notes: Separate Opus API call with transcript passed as context
       message. Two roundtrips. Same AdvisorResponse contract.
       Loses single-call cost advantage.
```

The implementation makes a standalone call to Opus, passing the full
transcript as input context. The response is mapped to the same
AdvisorResponse shape.

**Claude Code** *(future, P16)* declares ADVISE as native:

```
Capability: ADVISE
Mode: native
Cost: cheap
Notes: Uses Claude Code's native /advisor subagent or advisor tool
       when available. Falls back to emulated if native not yet shipped.
```

### Step 4 — Factory binding (Layer 1)

When the factory receives a request to create an agent for the `coder`
role, it:

1. Reads `required_capabilities: [ADVISE]` from the role config.
2. Checks which configured harnesses declare ADVISE with a mode other
   than `not_supported`.
3. Binds the role to a qualifying harness (selection algorithm is P11's
   responsibility; the factory contract only requires that the match is
   valid).
4. If no harness qualifies, raises an error identifying ADVISE as the
   unmet capability.

### Step 5 — Runtime execution (Layer 2 → Layer 3)

During an agent loop on Deep Agents:

1. The executor (Sonnet) runs normally — calling tools, reading
   results, iterating.
2. The executor's prompt instructs it: "when stuck on a non-obvious
   design decision or after repeated tool failures, call the `advisor`
   tool with your question."
3. When the executor calls `advisor(question="...")`, the tool handler
   invokes the ADVISE pattern implementation:
   - Collects the full transcript.
   - Calls AdvisorClient with the transcript + question.
   - Receives guidance from Opus.
   - Returns the guidance as the tool result.
4. The executor reads the guidance and resumes its loop.

### Step 6 — Transport-mediated mode (Layer 4, future)

When P6 `a2a-server` lands, a transport-mediated path becomes available:

1. A Claude Code session running the `coder` role hits a hard decision.
2. The Claude Code harness doesn't have native ADVISE (hypothetically).
3. The factory selected Claude Code anyway because the harness declared
   ADVISE as transport-mediated.
4. The harness sends an A2A message to the Deep Agents advisor endpoint.
5. Deep Agents processes the ADVISE pattern natively and returns the
   guidance over A2A.
6. The Claude Code harness receives the response and presents it to the
   executor.

This path is enumerated here but not implemented until P6/P17.

---

## Open Questions

- [ ] Should CapabilityInfo be immutable per harness, or can it change
  at runtime (e.g., a harness loses network connectivity and degrades
  from transport-mediated to not_supported)?
- [ ] Should the anti-pattern registry (D6) be a living document that
  downstream proposals append to, or a static snapshot?
- [ ] When P12 retrofits DELEGATE as a Capability, does the existing
  `spawn_sub_agent()` method on `HarnessAdapter` survive as the native
  implementation, or is it replaced entirely?
