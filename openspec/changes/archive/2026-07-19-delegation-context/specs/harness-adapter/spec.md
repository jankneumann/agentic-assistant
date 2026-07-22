# harness-adapter Specification (delta)

## MODIFIED Requirements

### Requirement: SDK Harness Adapter

The system SHALL define an `SdkHarnessAdapter` abstract base class
extending `HarnessAdapter` with `harness_type() → "sdk"` and requiring
the methods `create_agent(tools: list, extensions: list) → Any`,
`invoke(agent: Any, message: str) → str`,
`astream_invoke(agent: Any, message: str) → AsyncIterator[HarnessEvent]`,
and `spawn_sub_agent(role: RoleConfig, task: str, tools: list,
extensions: list, context: DelegationContext | None = None) → str`.
The `tools` parameter of `create_agent` (and
`spawn_sub_agent`) is the complete, already-aggregated tool list
produced by `ToolPolicy.authorized_tools()` — the tool policy is the
sole tool aggregator. Harness implementations MUST NOT re-aggregate,
re-derive, filter, or re-wrap extension tools from the `extensions`
argument; that parameter is retained for non-tool concerns only
(lifecycle hooks, health checks). This keeps aggregation at one seam
so a tool-search/ranking stage can slot into the tool policy without
touching any harness. The `astream_invoke` method is an additive
streaming variant of `invoke`; it MUST NOT replace or alter the
contract of the existing blocking `invoke` method, which remains
callable by the CLI REPL.

The `context` parameter of `spawn_sub_agent` (P12 delegation-context)
is ADDITIVE: `None` — including every pre-P12 call shape — MUST
preserve the prior behavior exactly, with the sub-agent's composed
prompt byte-identical to pre-P12 output. When a `DelegationContext`
is provided, the concrete harness MUST thread it to the sub-harness
and render `context.render()` as a `## Delegation context` block
prepended AHEAD of the D27 `## Recent context` section (when present)
and the composed system prompt, so the sub-agent reads its delegation
identity and constraints first.

#### Scenario: SdkHarnessAdapter.create_agent consumes the aggregated tool list as-is

- **WHEN** `create_agent(tools, extensions)` is called on any concrete
  `SdkHarnessAdapter` implementation
- **THEN** the harness MUST construct an agent whose tool set is
  exactly the provided `tools` (rendered to the harness's native tool
  shape as needed)
- **AND** the harness MUST NOT derive additional tools from
  `extensions`

#### Scenario: SdkHarnessAdapter.invoke signature unchanged

- **WHEN** `invoke(agent, message)` is called
- **THEN** the returned value MUST be a string containing the agent's
  response

#### Scenario: SdkHarnessAdapter.astream_invoke returns async iterator of HarnessEvent

- **WHEN** `astream_invoke(agent, message)` is called on any concrete
  `SdkHarnessAdapter` implementation
- **THEN** the returned value MUST be an async iterator yielding
  `HarnessEvent` instances
- **AND** the stream MUST begin with a `RunStarted` event and end with
  a `RunFinished` event in every successful execution

#### Scenario: SdkHarnessAdapter exposes a thread_id for transport binding

- **WHEN** any concrete `SdkHarnessAdapter` instance is constructed by
  the harness factory
- **THEN** it MUST expose a stable `thread_id` attribute (or
  property) returning a non-empty string identifying the conversation
  thread bound to that adapter instance
- **AND** the value MUST persist for the lifetime of the adapter
  instance (i.e., across multiple `invoke` and `astream_invoke` calls)
- **AND** the value MUST be readable by the web transport layer (the
  SSE handler passes it to the AG-UI mapper as the `thread_id`
  keyword argument); harnesses MAY synthesize it (e.g., MSAF
  generates a UUID at construction) or derive it from an existing
  internal field (e.g., Deep Agents reuses `self._thread_id` already
  wired by the conversation-memory requirement)

#### Scenario: spawn_sub_agent renders the delegation context block

- **WHEN** `spawn_sub_agent(role, task, tools, extensions,
  context=<DelegationContext>)` is awaited on either SDK harness
- **THEN** the sub-agent's composed system prompt MUST contain the
  `## Delegation context` block
- **AND** the block MUST appear before the `## Recent context`
  section (when snippets exist) and before the composed role prompt

#### Scenario: spawn_sub_agent without context preserves pre-P12 output

- **WHEN** `spawn_sub_agent(role, task, tools, extensions)` is
  awaited with no context
- **THEN** the sub-agent's composed system prompt MUST NOT contain
  `## Delegation context` and MUST equal the pre-P12 composition
