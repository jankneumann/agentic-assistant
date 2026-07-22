# delegation-spawner Specification (delta)

## ADDED Requirements

### Requirement: Delegation Chain Attribution and Depth Limit

The `DelegationSpawner` SHALL carry an `AgentIdentity` for the parent
principal — accepted via an optional `identity` constructor parameter
(a nested spawner receives the already-extended identity of its hop),
or synthesized from the persona name, parent role name, and the
harness `thread_id` when available. For every `delegate()` call the
spawner SHALL derive the child principal via
`identity.delegate_to(sub_role)` and enforce the persona's
`guardrails.delegation.max_chain_depth` ceiling (default `5`, `0` =
unlimited, applied even for personas without a `guardrails:`
section): a hop whose child chain depth would exceed the ceiling MUST
raise `PermissionError` with a reason naming the ceiling and the full
chain, BEFORE the guardrail `check_delegation` call and without
spawning. The spawner SHALL log the delegation chain on every
decision and SHALL emit a guardrail audit record (per the
agent-identity capability) for both depth denials and
`check_delegation` outcomes, carrying the parent identity and the
proposed child chain. Existing ACL ordering is preserved: the
`allowed_sub_roles` and persona-availability `ValueError` checks
still run first.

#### Scenario: Root identity is synthesized

- **WHEN** a `DelegationSpawner` is constructed without an `identity`
- **THEN** its identity MUST carry the persona name, the parent role
  name, and an empty delegation chain

#### Scenario: Hop exceeding the ceiling is denied with the chain

- **WHEN** the spawner's identity already carries 5 delegation hops
  and `max_chain_depth` is 5
- **AND** `delegate()` is called for an allowed sub-role
- **THEN** `PermissionError` MUST be raised naming `max_chain_depth`
  and the chain
- **AND** `spawn_sub_agent` MUST NOT be called
- **AND** an audit record with decision `deny` MUST be emitted

#### Scenario: Allowed hop is audited with the chain

- **WHEN** a delegation passes the ACL, depth, and guardrail checks
- **THEN** exactly one audit record with decision `allow` MUST be
  emitted carrying the delegation action type, the sub-role as the
  resource, and the parent identity's chain

#### Scenario: Chains extend hop by hop

- **WHEN** a spawner at chain `()` for role `researcher` delegates,
  and a nested spawner is constructed with the child identity for
  role `coder`
- **THEN** the nested spawner's next child identity MUST carry the
  chain `("researcher", "coder")` and depth `2`
