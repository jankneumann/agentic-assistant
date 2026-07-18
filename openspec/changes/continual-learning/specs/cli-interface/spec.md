# cli-interface Specification (delta)

## ADDED Requirements

### Requirement: CLI feedback Command

The system SHALL provide an `assistant feedback -p <persona> [-r
<role>] [--prefer [category:]key=value] [TEXT]` command recording one
human `FeedbackEvent` through the persona's memory (interactions
table, `metadata.source=feedback`). At least one of `TEXT` or
`--prefer` MUST be supplied; `--prefer` attaches a structured
preference payload (`category` defaults to `general`) that later
distills into a LOW-risk `preference` proposal. The command MUST fail
with exit code 1 and an actionable message for a persona whose
learning config is falsy (dormant) or that has no `database_url`.

#### Scenario: Feedback records a labeled event

- **WHEN** `assistant feedback -p learning_lab -r coder "too wordy"`
  runs
- **THEN** the command exits 0 and one interaction row is stored with
  `metadata.source="feedback"` and subject `role:coder`

#### Scenario: Dormant persona refuses feedback

- **WHEN** `assistant feedback -p personal "nice"` runs for a persona
  without a `learning:` section
- **THEN** the command exits 1 naming the dormant learning config

### Requirement: CLI reflect Command

The system SHALL provide an `assistant reflect -p <persona>` command
running one reflection/consolidation pass and printing either the
consolidated fact key and interaction count or a nothing-new notice.
It MUST refuse (exit 1, actionable message) for dormant personas and
personas without a `database_url`.

#### Scenario: Reflect consolidates new interactions

- **WHEN** `assistant reflect -p learning_lab` runs with stored
  interactions present
- **THEN** the command exits 0 and reports the consolidated count and
  the `learning/reflection/*` fact key

### Requirement: CLI learning Command Group

The system SHALL provide an `assistant learning` command group with
four subcommands driving the P28 pipeline:

- `learning collect -p <persona> [--gate-log <file>] [--store]` —
  runs the machine collectors on demand, printing one line per event;
  `--store` additionally records them as stored feedback.
- `learning propose -p <persona> [--gate-log <file>] [--limit N]` —
  derives proposals from stored + machine feedback and writes one
  JSON file per proposal into the persona's proposals directory,
  then runs the opt-in LOW-preference auto-apply path (persisting any
  status change). Without a `database_url` it proceeds machine-only
  with a warning.
- `learning apply -p <persona> <proposal-ref> [--approved]` —
  resolves a proposal file path or id, runs the fully gated
  `apply_proposal`, and persists the applied status back to the
  proposal file.
- `learning list -p <persona>` — lists proposals with kind, risk,
  status, and target.

Every learning refusal (`LearningError` and subclasses) MUST surface
as an `Error:` message with exit code 1, never a traceback; all
subcommands MUST refuse dormant personas.

#### Scenario: Propose writes reviewable proposal files

- **WHEN** `assistant learning propose -p learning_lab --gate-log
  <log with a FAIL line>` runs
- **THEN** the command exits 0 and a `prompt_layer` proposal JSON
  file exists in the persona's proposals directory

#### Scenario: Apply is gated

- **WHEN** `assistant learning apply -p learning_lab <low-pref-id>`
  runs with a passing eval gate
- **THEN** the command exits 0, stores the preference, and the
  proposal file's status becomes `applied`
- **AND** with a failing gate the command exits 1 naming the gate

#### Scenario: MEDIUM risk needs --approved

- **WHEN** a `prompt_layer` proposal is applied without `--approved`
- **THEN** the command exits 1 naming the approval flag

### Requirement: Feedback REPL Command

The interactive REPL SHALL accept a `/feedback <text>` command
recording one human feedback event about the active role (subject
`role:<active-role>`, context `repl`) through the same pipeline as
`assistant feedback`. A missing argument prints usage; a dormant
persona or missing database prints an `Error:` line without leaving
the REPL. The commands help line MUST advertise `/feedback <text>`.

#### Scenario: REPL feedback records and continues

- **WHEN** the user enters `/feedback stop apologising`
- **THEN** one feedback event is recorded and the REPL prints a
  confirmation and keeps running

#### Scenario: Dormant persona keeps the REPL alive

- **WHEN** `/feedback x` is entered for a persona without learning
  config
- **THEN** the REPL prints an `Error:` line and continues
