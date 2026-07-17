# persona-registry Specification (delta)

## ADDED Requirements

### Requirement: Harness Routing Rules Parsing

Persona load SHALL parse and validate an optional `harnesses.routing:`
list into `PersonaConfig.harness_routing` (an ordered tuple of
routing rules) and SHALL remove the `routing` key from
`PersonaConfig.harnesses` so that mapping remains strictly
harness-name → config. Each rule is a mapping with keys `role:`
(optional non-empty glob on the role name), `tools:` (optional
non-empty list of non-empty globs matched against role
`preferred_tools`), and `harness:` (required non-empty target name);
a rule MUST declare at least one of `role:`/`tools:`. Unknown keys,
wrong types, empty matchers, and a missing/empty `harness:` SHALL
fail persona load with an actionable error naming the persona, config
path, and rule index — the same posture as the `models:` /
`guardrails:` / `schedules:` sections. Registry-level validation of
the target name (unknown/host/disabled harness) is owned by
`select_harness` at selection time, because the persona registry
cannot import the harness factory (import-direction discipline). A
persona without a `harnesses.routing:` list SHALL load with an empty
rule tuple.

#### Scenario: Valid routing rules parse in order

- **WHEN** a persona declares
  `harnesses.routing: [{tools: ["ms_graph:*"], harness: ms_agent_framework}, {role: "*", harness: deep_agents}]`
- **THEN** `PersonaConfig.harness_routing` MUST contain the two rules
  in declaration order
- **AND** `"routing"` MUST NOT be a key of `PersonaConfig.harnesses`

#### Scenario: Rule without a matcher fails persona load

- **WHEN** a persona declares
  `harnesses.routing: [{harness: deep_agents}]`
- **THEN** persona load MUST raise an error containing
  `"invalid harnesses.routing: section"` and the rule index

#### Scenario: Unknown rule key fails persona load

- **WHEN** a rule declares a `model:` key
- **THEN** persona load MUST raise an error naming the unknown key
