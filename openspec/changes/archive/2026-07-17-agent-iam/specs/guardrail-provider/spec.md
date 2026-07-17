# guardrail-provider Specification (delta)

## MODIFIED Requirements

### Requirement: Guardrail Action Policies

The system SHALL evaluate `guardrails.policies` in declaration order
with first-match-wins semantics: a policy matches when its
`action_type` equals the request's action type (or is `"*"`), its
`resource` glob matches the request's resource, and its optional
identity-aware dimensions (P25 agent-iam, additive) are satisfied:

- `role` (default `"*"`) — a glob matched against the acting role:
  the request's `identity.role` when an `AgentIdentity` is attached,
  else the plain `ActionRequest.role` field;
- `min_chain_depth` (default `0` = no constraint) — the policy only
  matches requests whose identity carries at least this many
  delegation hops; a non-zero value MUST NOT match a request without
  an identity (depth cannot be established, so evaluation skips to
  the next policy rather than matching or denying).

Unknown policy keys MUST fail parse with an actionable error.
Effects: `deny` returns `allowed=False` with the policy's reason;
`require_confirmation` returns `allowed=True,
require_confirmation=True`; `allow` matches without bypassing budget
ceilings. For `model_call` actions, a `require_confirmation` decision
is treated as a denial by the model-binding budget hook until the
approval interrupt flow exists (the "Confirmation Requests Deny Until
Interrupt Flow Exists" requirement of the model-provider capability
is preserved unchanged — this change does NOT build interrupt or
resume).

#### Scenario: Deny policy blocks a matching resource

- **WHEN** a policy `{action_type: model_call, resource:
  "expensive-*", effect: deny}` is declared
- **AND** `check_action` is called for resource `expensive-opus`
- **THEN** the decision MUST have `allowed=False`
- **AND** a request for resource `cheap-model` MUST be allowed

#### Scenario: First matching policy wins

- **WHEN** an allow policy for resource `special` precedes a deny
  policy for resource `*`
- **THEN** `check_action` for `special` MUST allow
- **AND** `check_action` for any other resource MUST deny

#### Scenario: require_confirmation on model_call denies at the binding

- **WHEN** a `require_confirmation` policy matches a `model_call`
  request
- **AND** the model binding's `check_model_call` hook consumes the
  decision
- **THEN** the dispatch MUST be refused with an error naming the
  confirmation requirement

#### Scenario: Role dimension matches the acting identity

- **WHEN** a policy `{action_type: model_call, role: "research*",
  effect: deny}` is declared
- **AND** `check_action` is called with an identity whose role is
  `researcher`
- **THEN** the decision MUST have `allowed=False`
- **AND** the same request with an identity role of `coder` MUST be
  allowed

#### Scenario: Depth-scoped policy skips identity-less requests

- **WHEN** a policy with `min_chain_depth: 2` and `effect: deny` is
  declared
- **AND** `check_action` is called with an identity at chain depth 2,
  one at depth 1, and one with no identity
- **THEN** only the depth-2 request MUST be denied
- **AND** the depth-1 and identity-less requests MUST be allowed

### Requirement: Delegation Constraints

The system SHALL enforce `guardrails.delegation` in
`check_delegation`, preserving the existing consumer contract (the
delegation spawner raises `PermissionError` when `allowed=False`):
a sub-role matching any `denied_sub_roles` glob is denied with a
reason naming the pattern, and a task longer than a non-zero
`max_task_chars` is denied. All other delegations are allowed. The
section SHALL additionally carry `max_chain_depth` (P25 agent-iam;
default `5`, `0` = unlimited, validated as a non-negative number) —
the delegation-chain depth ceiling consumed by the delegation
spawner (chain enforcement is a property of the spawner's
`AgentIdentity`, not of the `check_delegation` signature, which is
unchanged). The `max_chain_depth` default MUST NOT make an otherwise
empty `GuardrailConfig` truthy — resolver guardrail selection is
unchanged.

#### Scenario: Denied sub-role glob blocks delegation

- **WHEN** `denied_sub_roles: ["cod*"]` is configured
- **AND** `check_delegation("chief_of_staff", "coder", task)` is
  called
- **THEN** the decision MUST have `allowed=False`
- **AND** delegation to `writer` MUST be allowed

#### Scenario: Spawner surfaces the denial

- **WHEN** the delegation spawner consumes a denied decision
- **THEN** it MUST raise `PermissionError` before loading the
  sub-role

#### Scenario: max_chain_depth parses with a safe default

- **WHEN** a persona declares no `guardrails:` section (or one
  without `delegation.max_chain_depth`)
- **THEN** the parsed constraint MUST default to `5`
- **AND** the parsed `GuardrailConfig` MUST remain falsy so the
  resolver still selects `AllowAllGuardrails`

#### Scenario: Negative max_chain_depth fails parse

- **WHEN** `delegation: {max_chain_depth: -3}` is declared
- **THEN** parsing MUST raise an error naming `max_chain_depth`
