# harness-adapter Specification (delta)

## ADDED Requirements

### Requirement: Automatic Harness Selection

The system SHALL provide a `select_harness(persona, role, *,
requested=None)` function in `harnesses/factory.py` that
deterministically resolves the harness name for a persona × role
composition without any LLM call, with the following precedence:

1. An explicit `requested` harness name (any value other than `None`
   or the `auto` sentinel) SHALL be returned verbatim — explicit
   selection always bypasses routing (enablement validation remains
   `create_harness`'s job).
2. The persona's ordered `harnesses.routing:` rules SHALL be
   evaluated first-match: a rule matches when its `role:` glob (when
   declared) matches the role name AND (when declared) any of its
   `tools:` globs matches any role `preferred_tools` entry. A
   `tools:` pattern containing `:` matches the full
   `source:operation` string; a bare pattern matches the source
   prefix. A matching rule whose target harness is not enabled for
   the persona SHALL be skipped with a WARNING and evaluation SHALL
   continue; a matching rule naming an unregistered harness or a host
   harness SHALL raise `ValueError`.
3. Built-in defaults SHALL apply when no rule matches: when any role
   `preferred_tools` entry references an MS tool source (`ms_graph`,
   `outlook`, `teams`, `sharepoint`) and `ms_agent_framework` is
   enabled, the result is `ms_agent_framework`; otherwise
   `deep_agents` when enabled; otherwise the remaining enabled SDK
   harness; otherwise `ValueError` naming the persona and pointing at
   explicit host-tier selection.

A host harness MUST NOT ever be returned by rules or built-in
defaults — host harnesses export configuration rather than execute,
so auto-selecting one would silently no-op an interactive run; the
host (subscription) tier is reachable only by explicit request.

#### Scenario: Explicit request bypasses routing

- **WHEN** `select_harness(persona, role, requested="deep_agents")`
  is called for a persona whose routing rules would select
  `ms_agent_framework`
- **THEN** the returned name MUST equal `"deep_agents"`

#### Scenario: MS-source preferred_tools route to MSAF

- **WHEN** the role's `preferred_tools` contains `outlook:send_mail`
- **AND** `persona.harnesses["ms_agent_framework"]["enabled"]` is true
- **AND** `select_harness(persona, role)` is called with no routing
  rules declared
- **THEN** the returned name MUST equal `"ms_agent_framework"`

#### Scenario: MS-tool role falls back when MSAF is disabled

- **WHEN** the role's `preferred_tools` contains `ms_graph:list_users`
- **AND** `ms_agent_framework` is not enabled for the persona
- **AND** `deep_agents` is enabled
- **THEN** `select_harness(persona, role)` MUST return `"deep_agents"`

#### Scenario: Persona routing rules match first

- **WHEN** the persona declares
  `harnesses.routing: [{role: "coder", harness: ms_agent_framework}]`
- **AND** `ms_agent_framework` is enabled
- **AND** `select_harness(persona, coder_role)` is called
- **THEN** the returned name MUST equal `"ms_agent_framework"` even
  though the role prefers no MS-source tools

#### Scenario: Matching rule with disabled target is skipped

- **WHEN** the first routing rule matches but names a harness with
  `enabled: false`
- **AND** a later rule (or the built-in default) yields an enabled
  harness
- **THEN** `select_harness` MUST return the later result
- **AND** a WARNING naming the skipped rule MUST be logged

#### Scenario: Rule targeting a host harness raises

- **WHEN** a matching routing rule declares `harness: claude_code`
- **THEN** `select_harness` MUST raise `ValueError` indicating host
  harnesses cannot be auto-selected

#### Scenario: Host harness never auto-selected by defaults

- **WHEN** only `claude_code` is enabled for the persona
- **AND** `select_harness(persona, role)` is called
- **THEN** `ValueError` MUST be raised rather than returning
  `"claude_code"`

### Requirement: Harness Routing Decision Telemetry

Every `select_harness` resolution SHALL emit exactly one
`harness.routing` span through the observability provider's
`start_span` escape hatch, carrying attributes for the persona name,
role name, requested value (or `auto`), selected harness, and the
selection reason (`explicit`, a rule reference, or a
`builtin:*` label), and SHALL log one INFO line with the same facts.
Emission MUST be defensive: a failing telemetry provider logs a
WARNING and MUST NOT change the selection outcome.

#### Scenario: Routing decision emits a span

- **WHEN** `select_harness(persona, role)` resolves to
  `"deep_agents"` via the built-in default
- **THEN** `start_span` MUST be called once with the span name
  `"harness.routing"`
- **AND** the attributes MUST include `selected == "deep_agents"`
  and a `reason` beginning with `"builtin:"`

#### Scenario: Telemetry failure does not break selection

- **WHEN** the observability provider's `start_span` raises
- **THEN** `select_harness` MUST still return the selected harness
- **AND** a WARNING MUST be logged
