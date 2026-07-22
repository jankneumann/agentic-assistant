# mcp-server Specification (delta)

## MODIFIED Requirements

### Requirement: MCP Session Multiplexing

The system SHALL multiplex MCP tool calls over per-role session
registries (the harness-adapter Session Registry contract): a call
without `context_id` MUST create a fresh session (a new harness +
agent built through the same persona/role pipeline as the AG-UI and
A2A surfaces); a call with a known `context_id` MUST reuse that
session (serialized per-session so concurrent calls do not interleave
turns). A call whose `context_id` is not live in-process MUST be
resolved through the registry's durable re-bind path when the persona
has durable sessions configured (a known-active, un-lapsed metadata
row for the SAME role is re-bound with the recorded `thread_id`; the
durable checkpointer restores the conversation) and MUST be rejected
as a tool error only when the id is truly unknown, lapsed,
role-foreign, or the persona has no durable tier — never by silently
creating a session. Each `ask_<role>` tool's sessions MUST be bound
to that role.

#### Scenario: Fresh session per contextless call

- **WHEN** `ask` is called twice without `context_id`
- **THEN** two distinct sessions MUST be created
- **AND** the two results MUST carry distinct `context_id` values

#### Scenario: Known context continues the conversation

- **WHEN** `ask` is called with the `context_id` returned by a prior
  call
- **THEN** the same session MUST serve the second call
- **AND** no new session MUST be created

#### Scenario: Released context is re-bound on a durable persona

- **WHEN** the durable tier is configured and a session is expired
  in-process
- **AND** `ask` is called with that session's `context_id`
- **THEN** the call MUST be served on a harness re-bound to the same
  `context_id` rather than rejected

#### Scenario: Unknown context is rejected

- **WHEN** `ask` is called with `context_id="never-created"`
- **THEN** the result MUST carry `isError=true` naming the unknown
  context id
- **AND** no session MUST be created

#### Scenario: Role tools run role-bound sessions

- **WHEN** `ask_researcher` is called without `context_id`
- **THEN** the created session's harness MUST be constructed with the
  `researcher` role
