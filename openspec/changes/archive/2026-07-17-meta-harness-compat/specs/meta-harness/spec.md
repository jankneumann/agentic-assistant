# meta-harness Specification (delta)

## ADDED Requirements

### Requirement: Omnigent Agent Definition Content

The system SHALL build an Omnigent-shaped agent definition describing
the assistant as an externally-served composable agent: name, display
name, and description from the persona; A2A endpoints (agent card +
JSON-RPC), the MCP streamable-HTTP endpoint with the `ask` tool plus
one `ask_<role>` per enabled role, and the AG-UI chat/health endpoints
— all derived from a caller-supplied base URL; the persona's P25
`auth.a2a` declaration SHAPE (scheme and credential ref name only,
never a token value) or an explicit none-declared note; and one skill
per enabled role mirroring the A2A agent card.

#### Scenario: Endpoints derive from the base URL

- **WHEN** a definition is built with base URL `http://gx10:8765`
- **THEN** it MUST reference
  `http://gx10:8765/.well-known/agent-card.json`,
  `http://gx10:8765/a2a/v1`, `http://gx10:8765/mcp`, and
  `http://gx10:8765/chat`

#### Scenario: Auth shape never carries a secret

- **WHEN** the persona declares `auth.a2a: {type: bearer, token_env:
  A2A_TOKEN}`
- **THEN** the definition MUST carry the scheme type and the ref name
  `A2A_TOKEN`
- **AND** no resolved token value may appear anywhere in the output

### Requirement: Unverified Schema Marking

The system SHALL mark every rendered Omnigent agent definition as
Omnigent-shaped but schema-unverified: the YAML header MUST instruct
the operator to verify the structure against the canonical
`omnigent-ai/omnigent` schema on a connected machine, and the
definition body MUST carry a machine-readable
`schema_verified: false` marker until such verification changes the
generator.

#### Scenario: Rendered YAML carries the verification header

- **WHEN** a definition is rendered to YAML
- **THEN** the output MUST begin with a header naming
  `omnigent-ai/omnigent` and instructing verification on a connected
  machine
- **AND** the parsed body MUST contain a `schema_verified: false`
  marker
