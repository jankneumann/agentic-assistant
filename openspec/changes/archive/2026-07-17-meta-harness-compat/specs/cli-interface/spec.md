# cli-interface Specification (delta)

## ADDED Requirements

### Requirement: CLI export-omnigent-agent Command

The system SHALL provide an `assistant export-omnigent-agent`
command (joining the flat export family) that renders the
Omnigent-shaped agent-definition YAML for a required `-p/--persona`,
deriving endpoint URLs from `--base-url` (default
`http://127.0.0.1:8765`), printing to stdout by default and writing
to a file when `-o/--output` is given.

#### Scenario: Definition prints to stdout

- **WHEN** `assistant export-omnigent-agent -p personal --base-url
  http://h:1` runs
- **THEN** stdout MUST be parseable YAML whose A2A RPC endpoint is
  `http://h:1/a2a/v1`

#### Scenario: Output flag writes a file

- **WHEN** the command runs with `-o agent.yaml`
- **THEN** the file MUST be written containing the unverified-schema
  header

#### Scenario: Persona is required

- **WHEN** the command runs without `-p`
- **THEN** it MUST exit nonzero with a usage error naming the persona
  option
