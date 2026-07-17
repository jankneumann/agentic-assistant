# agent-identity Specification

## Purpose
TBD - created by archiving change agent-iam. Update Purpose after archive.
## Requirements
### Requirement: AgentIdentity Principal

The system SHALL define an `AgentIdentity` frozen dataclass in
`core/capabilities/` — the principal answering "who is acting?" for
guardrail decisions — with fields `persona: str`, `role: str`,
`delegation_chain: tuple[str, ...]` (ancestor ROLE names, root-first,
excluding the current role; `()` for a root identity), `session_id:
str` (harness `thread_id` / A2A `contextId` when known, else `""`),
and `issued_at: datetime` (UTC, defaulting to construction time). The
type SHALL expose `chain_depth` (the number of delegation hops,
`len(delegation_chain)`) and `delegate_to(sub_role) → AgentIdentity`,
which derives the child principal for one hop: persona inherited
(delegation switches role, never persona), the parent's role appended
to the chain, the session id carried through, and a fresh
`issued_at`. Instances MUST be immutable — chain extension always
produces a new principal. The shape is a deliberate SPIFFE-shaped
placeholder (protocol-standards matrix, auth row): no converged
standard for agent identity exists, so migration to a workload-
identity document must be a field mapping, not a rewrite.

#### Scenario: Identity is immutable

- **WHEN** field assignment is attempted on a constructed
  `AgentIdentity`
- **THEN** it MUST raise `FrozenInstanceError`
- **AND** the delegation chain MUST be a tuple (not mutable in place)

#### Scenario: delegate_to extends the chain

- **WHEN** a root identity `(persona=p, role=chief_of_staff,
  chain=())` delegates to `researcher` and that child delegates to
  `writer`
- **THEN** the grandchild MUST have `role == "writer"`,
  `delegation_chain == ("chief_of_staff", "researcher")`, and
  `chain_depth == 2`
- **AND** the persona and session id MUST be inherited unchanged
- **AND** the parent identities MUST be unmodified

### Requirement: ActionRequest Identity Attachment

The `ActionRequest` dataclass SHALL carry an optional `identity:
AgentIdentity | None` field defaulting to `None`, so every existing
construction site keeps working unchanged. The identity SHALL be
populated at these construction sites: the delegation spawner's
guardrail checks, the model-call guardrail hook
(`core/capabilities/model_bindings.py check_model_call` — which
synthesizes `AgentIdentity(persona, role)` from its existing string
arguments when no identity is injected), and both SDK harnesses'
`spawn_sub_agent` delegate checks (with `session_id` set to the
harness `thread_id`).

#### Scenario: Default stays None

- **WHEN** an `ActionRequest` is constructed without an `identity`
  argument
- **THEN** `request.identity` MUST be `None`

#### Scenario: Model-call hook synthesizes an identity

- **WHEN** `check_model_call(guardrails, ref, persona="p",
  role="coder")` is called without an injected identity
- **THEN** the `ActionRequest` passed to `check_action` MUST carry an
  `AgentIdentity` with `persona == "p"`, `role == "coder"`, and an
  empty delegation chain

### Requirement: Guardrail Decision Audit Records

The system SHALL emit a structured audit record for every guardrail
decision whose `ActionRequest` carries an `AgentIdentity`, through
the EXISTING telemetry provider's `start_span` escape hatch (span
name `guardrail.decision`) — the closed first-class trace-op
vocabulary is untouched and telemetry is the sink (no separate audit
store; a durable audit log is deferred with the approval interrupt
flow). The record's attributes SHALL include `action_type`,
`resource`, `persona`, `role`, `delegation_chain` (root-first list),
`chain_depth`, `session_id`, `issued_at`, `decision` (one of `allow`,
`deny`, `require_confirmation`), and `reason`. Requests WITHOUT an
identity MUST NOT emit audit records (pre-P25 call sites are
unaffected), and audit emission MUST never raise into the caller — a
failing provider degrades to a WARNING while the enforcement outcome
stands.

#### Scenario: Attributable decision emits one record

- **WHEN** a guardrail decision is made for a request carrying an
  identity with chain `("chief_of_staff",)`
- **THEN** exactly one `guardrail.decision` span MUST be emitted
- **AND** its attributes MUST include the persona, role, chain,
  depth, and the decision outcome string

#### Scenario: Identity-less request is not audited

- **WHEN** a guardrail decision is made for a request with
  `identity=None`
- **THEN** no audit span MUST be emitted

#### Scenario: Telemetry failure does not change enforcement

- **WHEN** the telemetry provider raises from `start_span`
- **THEN** the guardrail decision MUST still be returned/enforced
  normally
- **AND** the failure MUST be logged as a WARNING

