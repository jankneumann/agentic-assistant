# ms-agent-framework-harness

## MODIFIED Requirements

### Requirement: Memory Snippet Injection in create_agent

The system SHALL inject the persona's recent memory snippets into the
constructed `Agent`'s `instructions` parameter at `create_agent`
time. The harness SHALL await the configured async
`MemoryPolicy.get_recent_snippets(persona, role, limit=N)` (where N
defaults to 10) directly on the `create_agent` event loop (owner
review verdict C8, 2026-07-16 — no sync-to-async bridge on the hot
path), and SHALL prepend the resulting text block to the
composed system prompt under a clearly demarcated section heading
(`## Recent context`). When the persona has no `MemoryPolicy`
configured, or the policy returns an empty list, no section MUST be
injected and the instructions MUST equal the composed prompt
unchanged.

As of `memory-retrieval-activation` (P21) the built-in policies return
**live** snippets: `PostgresGraphitiMemoryPolicy` retrieves recent
facts, preferences, interaction summaries, and Graphiti semantic
results via `MemoryManager.get_recent_snippets`;
`FileMemoryPolicy` returns bounded `memory.md` excerpts. The
DeepAgents harness performs the identical prepend, so the two SDK
harnesses are symmetric.

**Follow-up scope** — the prepend remains the *only* injection
mechanism. A higher-fidelity integration (live retrieval mid-turn,
structured memory items rather than concatenated text) still requires
a structured memory hook on the `agent-framework` SDK that does not
exist in the SDK version pinned by P5; revisit when the SDK exposes a
memory injection point with a stable contract. Post-turn write-back of
completed turns is now covered by the harness-adapter capability's
"SDK Harness Post-Turn Memory Capture" requirement.

#### Scenario: Memory snippets prepended to instructions

- **WHEN** `MemoryPolicy.get_recent_snippets(persona, role,
  limit=10)` returns `["snippet-1", "snippet-2"]`
- **AND** `compose_system_prompt(persona, role)` returns
  `"You are work assistant."`
- **AND** `create_agent(...)` is awaited
- **THEN** the constructed `Agent`'s `instructions` MUST contain the
  substring `"## Recent context"`
- **AND** the instructions MUST contain both `"snippet-1"` and
  `"snippet-2"`
- **AND** the original prompt `"You are work assistant."` MUST also
  appear

#### Scenario: Empty memory snippets leaves instructions unchanged

- **WHEN** `MemoryPolicy.get_recent_snippets(...)` returns `[]`
- **AND** `compose_system_prompt(persona, role)` returns
  `"You are work assistant."`
- **AND** `create_agent(...)` is awaited
- **THEN** the constructed `Agent`'s `instructions` MUST equal
  `"You are work assistant."`
- **AND** the substring `"## Recent context"` MUST NOT appear in the
  instructions

#### Scenario: NoopMemoryPolicy yields no injection

- **WHEN** the persona has no `MemoryPolicy` configured (default
  noop policy is active)
- **AND** `create_agent(...)` is awaited
- **THEN** the harness MUST NOT call `get_recent_snippets` at all
  (or MUST treat the noop result as empty)
- **AND** the constructed `Agent`'s `instructions` MUST equal the
  composed prompt unchanged
