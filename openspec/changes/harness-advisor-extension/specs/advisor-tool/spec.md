# Spec: advisor-tool (delta)

## ADDED Requirements

### Requirement: AdvisorClient Direct SDK

The framework SHALL provide an AdvisorClient that calls the Anthropic
Messages API directly using the `advisor_20260301` tool type and the
`anthropic-beta: advisor-tool-2026-03-01` header.

#### Scenario: advisor call with full transcript

WHEN AdvisorClient.call() is invoked with a transcript and a question
THEN the client SHALL send the full transcript (including tool results)
to the advisor model
AND the response SHALL contain guidance text, model identity, input token
count, output token count, and duration in milliseconds.

#### Scenario: transcript is never summarized

WHEN AdvisorClient.call() is invoked
THEN the transcript passed to the API SHALL be the unmodified executor
conversation history
AND no summarization, truncation, or compression SHALL be applied to the
transcript before sending (per anti-pattern AP1).

#### Scenario: budget caps response not input

WHEN a budget_tokens parameter is provided
THEN the client SHALL use it to limit the advisor response length
AND the client SHALL NOT use it to truncate the input transcript.

---

### Requirement: AdvisorTool LangChain Integration

The framework SHALL provide an AdvisorTool as a LangChain StructuredTool
that wraps AdvisorClient for use in agent tool loops.

#### Scenario: tool invocation during agent loop

WHEN the executor LLM emits a tool_use for the advisor tool with a
question parameter
THEN the tool handler SHALL collect the full transcript from agent state
AND call AdvisorClient.call() with the transcript and question
AND return the advisor guidance as the tool result.

#### Scenario: tool is opt-in per role

WHEN a role does not declare ADVISE in required_capabilities
THEN the AdvisorTool SHALL NOT be added to the agent tool list
AND the agent loop SHALL behave identically to pre-P1.7 behavior.

---

### Requirement: Emulated Advisor Fallback

The framework SHALL provide an emulated advisor implementation for
harnesses that cannot use the advisor_20260301 tool type natively.

#### Scenario: emulated path produces same response shape

WHEN a harness declares Capability.ADVISE with mode emulated
THEN the advisor call SHALL produce an AdvisorResponse with the same
fields as the native implementation (guidance, model, tokens_in,
tokens_out, duration_ms).

#### Scenario: emulated path uses full transcript

WHEN the emulated advisor path is invoked
THEN the full executor transcript SHALL be passed as context
AND no summarization SHALL be applied (per anti-pattern AP1).
