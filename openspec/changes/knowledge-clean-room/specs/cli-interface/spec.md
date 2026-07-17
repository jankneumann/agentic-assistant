# cli-interface Specification (delta)

## ADDED Requirements

### Requirement: CLI cleanroom Command Group

The system SHALL provide an `assistant cleanroom` command group with
four subcommands driving the P26 declassification gateway:

- `cleanroom export -p <persona> --to <audience>` — runs
  `export_shared` and prints the bundle path, id, item count, and
  profile.
- `cleanroom import -p <persona> <bundle>` — runs `import_shared` on
  a bundle file path and prints the imported/skipped counts and
  source persona.
- `cleanroom revoke -p <persona> <bundle-id>` — runs `revoke`
  (source persona only) and prints the revocation record path.
- `cleanroom sync -p <persona>` — runs `purge_revoked` and prints the
  number of purged items.

Commands needing the persona's memory database (`export`, `import`,
`sync`) MUST fail with exit code 1 and an actionable message when the
persona has no `database_url`. Guardrail selection MUST mirror the
capability resolver (truthy `guardrails:` config selects
`PolicyGuardrails`, else `AllowAllGuardrails`), and each command MUST
act under a synthesized `AgentIdentity(persona, default_role)`. Every
clean-room refusal (`CleanRoomError` and subclasses) MUST surface as
an `Error:` message with exit code 1, never a traceback.

#### Scenario: Export writes a bundle into the shared space

- **WHEN** `assistant cleanroom export -p alpha --to beta` runs for a
  persona with a matching share rule
- **THEN** the command exits 0, prints the exported item count, and a
  bundle file exists under the shared space's `beta/` directory

#### Scenario: Import and sync complete the revocation loop

- **WHEN** a consumer imports a bundle, the source persona revokes
  it, and the consumer runs `cleanroom sync`
- **THEN** the sync exits 0 and reports the purged item count
- **AND** a subsequent import of the same bundle exits 1 naming the
  revocation

#### Scenario: Missing database_url fails actionably

- **WHEN** `cleanroom export` runs for a persona without a
  `database_url`
- **THEN** the command exits 1 with a message naming the missing
  configuration
