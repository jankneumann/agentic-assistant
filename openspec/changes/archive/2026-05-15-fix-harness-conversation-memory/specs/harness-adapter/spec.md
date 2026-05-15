# harness-adapter

## ADDED Requirements

### Requirement: Multi-Turn Conversation Memory

The `DeepAgentsHarness` SHALL preserve conversation history across
successive `invoke` calls on a single harness instance by
constructing its underlying agent with a `checkpointer` and passing a
stable `thread_id` in the invocation `config` on every call. The
`thread_id` MUST be generated once per harness instance (at
`create_agent` time) and MUST NOT change between `invoke` calls on
that instance. A new harness instance MUST be assigned a new,
distinct `thread_id` so that role-switch rebuilds (which construct a
fresh harness) start a fresh conversation.

#### Scenario: create_agent constructs the agent with a checkpointer

- **WHEN** `DeepAgentsHarness(persona, role).create_agent(tools, extensions)`
  is called
- **THEN** the `create_deep_agent` factory MUST receive a non-None
  `checkpointer` keyword argument
- **AND** `self._thread_id` MUST be set to a non-empty string

#### Scenario: invoke passes the harness thread_id on every call

- **WHEN** `DeepAgentsHarness.invoke(agent, message)` is called
- **THEN** the call to `agent.ainvoke` MUST include a `config` argument
  whose `configurable.thread_id` field equals `self._thread_id`

#### Scenario: A second invoke on the same harness sees prior history

- **WHEN** `DeepAgentsHarness.invoke(agent, "first turn")` is called
- **AND** `DeepAgentsHarness.invoke(agent, "second turn")` is called
  immediately after on the same harness instance and same agent
- **THEN** the messages list the model receives on the second call
  MUST contain both the user message `"first turn"` and the assistant
  response to the first turn
- **AND** the model receives the new user message `"second turn"`
  appended to that history

#### Scenario: Two harness instances have distinct thread_ids

- **WHEN** two separate `DeepAgentsHarness` instances each call
  `create_agent(tools, extensions)`
- **THEN** `harness_a._thread_id` MUST NOT equal `harness_b._thread_id`
- **AND** invoking `harness_b` MUST NOT see any messages produced by
  invoking `harness_a` (the two threads are isolated)
