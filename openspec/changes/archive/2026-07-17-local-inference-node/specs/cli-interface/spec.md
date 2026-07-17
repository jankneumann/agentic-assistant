# cli-interface Specification (delta)

## ADDED Requirements

### Requirement: CLI models Command Group

The CLI SHALL provide a `models` command group with two subcommands.
`assistant models sync-catalog -p <persona> [--url <base>]` SHALL
fetch the OpenRouter `/models` catalog (default URL
`https://openrouter.ai/api/v1/models`, overridable) using the
persona-scoped credential `OPENROUTER_API_KEY` when present, write the
persona-local catalog cache file, and print the model count and cache
path; any fetch failure (network unreachable, redirect, oversize
response, HTTP error) SHALL exit non-zero with an error naming the
cause. `assistant models check-health -p <persona>` SHALL probe every
registry entry that declares a `health:` block, print one line per
entry with its healthy/unhealthy verdict and probe URL, warm the
process's shared health cache, and exit `0` when all probed entries
are healthy (or none declare health checks, with a message saying so)
and `1` when any entry is unhealthy.

#### Scenario: models group is registered

- **WHEN** `assistant models --help` is executed
- **THEN** the exit code MUST be 0
- **AND** the output MUST list `sync-catalog` and `check-health`

#### Scenario: sync-catalog writes the persona cache

- **WHEN** `assistant models sync-catalog -p <persona>` runs against
  a catalog endpoint returning two models
- **THEN** the persona's `.cache/models/catalog.json` MUST be written
  containing both model ids
- **AND** the output MUST name the cache path

#### Scenario: sync-catalog without network errors clearly

- **WHEN** the catalog URL is unreachable
- **THEN** the exit code MUST be non-zero
- **AND** the error output MUST name the transport failure

#### Scenario: check-health reports per-entry verdicts

- **WHEN** `assistant models check-health -p <persona>` runs for a
  persona with one healthy and one unhealthy health-declaring entry
- **THEN** the output MUST contain one verdict line per entry
- **AND** the exit code MUST be 1

#### Scenario: check-health with no health-declaring entries

- **WHEN** the persona's registry declares no `health:` blocks
- **THEN** the command MUST print that no entries declare health
  checks
- **AND** exit 0 without issuing any probe
