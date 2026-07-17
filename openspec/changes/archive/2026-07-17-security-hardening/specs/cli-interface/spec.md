# cli-interface Specification (delta)

## ADDED Requirements

### Requirement: Persona Hash-Extensions Subcommand

The CLI SHALL provide `assistant persona hash-extensions -p
<persona>` that hashes every `*.py` file in the persona's extensions
directory (SHA-256) and writes/overwrites the `manifest.yaml`
integrity manifest next to them, printing each written filename and
digest. When the extensions directory does not exist the command MUST
exit non-zero with an error naming the missing path. Regenerating the
manifest after an intentional extension edit is the documented
operator flow for the persona registry's verify-before-execute check.

#### Scenario: Manifest is generated for a persona

- **WHEN** `assistant persona hash-extensions -p personal` is
  executed for a persona whose extensions directory contains
  `gmail.py`
- **THEN** `manifest.yaml` MUST be written in that directory with a
  `hashes:` entry for `gmail.py`
- **AND** the output MUST list `gmail.py` with its digest

#### Scenario: Missing extensions directory fails

- **WHEN** the persona has no extensions directory on disk
- **THEN** the command MUST exit with a non-zero status
- **AND** the error output MUST name the missing directory
