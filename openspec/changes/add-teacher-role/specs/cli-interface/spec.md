# cli-interface

## ADDED Requirements

### Requirement: Teacher Method Flag

The CLI SHALL accept an optional `--method <name>` / `-m <name>`
argument whose value names a skill file (without extension) under
`roles/teacher/skills/`. The flag is valid only when the effective role
is `teacher`; supplying it with any other role SHALL raise
`click.UsageError`. Supplying a method name that is not among the
discoverable skill files SHALL also raise `click.UsageError` and
MUST list the available methods.

#### Scenario: Teacher method flag accepted with teacher role

- **WHEN** the CLI is invoked with `-p personal -r teacher --method feynman`
- **AND** `roles/teacher/skills/feynman.md` exists
- **THEN** CLI startup MUST succeed without raising `UsageError`
- **AND** the first user-turn MUST be prefixed with a system-level
  directive instructing the agent to use the Feynman method

#### Scenario: Teacher method flag rejected with non-teacher role

- **WHEN** the CLI is invoked with `-r coder --method feynman`
- **THEN** `click.UsageError` MUST be raised
- **AND** the error message MUST contain the substring
  `"--method"` and `"teacher"`

#### Scenario: Unknown method name rejected

- **WHEN** the CLI is invoked with `-r teacher --method nonexistent`
- **AND** `roles/teacher/skills/nonexistent.md` does NOT exist
- **THEN** `click.UsageError` MUST be raised
- **AND** the error message MUST list the available methods
  (`feynman`, `socratic`)

### Requirement: Methods REPL Command

The interactive REPL SHALL accept a `/methods` command that, when the
active role is `teacher`, lists the discoverable skill files
(filename without extension) with the currently active method marked
with a trailing `←`. When the active role is not `teacher`, the
command SHALL print a guard message and continue the REPL without
error.

#### Scenario: Teacher methods REPL command lists available methods

- **WHEN** the REPL is running with the `teacher` role active
- **AND** the user enters `/methods`
- **THEN** the output MUST list `feynman` and `socratic` on separate
  lines
- **AND** exactly one of them MUST have a trailing `←` marker if an
  active method is set
- **AND** the REPL MUST continue without error

#### Scenario: Methods command rejected when role is not teacher

- **WHEN** the REPL is running with any role other than `teacher`
  active
- **AND** the user enters `/methods`
- **THEN** the output MUST include a guard message naming the
  `teacher` role requirement
- **AND** the REPL MUST continue without error

### Requirement: Method REPL Switch

The interactive REPL SHALL accept a `/method <name>` command that,
when the active role is `teacher` and `<name>` matches an existing
skill file, updates the REPL's active method state and injects a
system-level directive into the next agent invocation instructing the
agent to summarize current progress, announce the switch, and enter
Step 1 of the new method. The command MUST NOT rebuild the harness or
agent instance (contrast with `/role <name>`). When `<name>` does not
match any skill, the REPL SHALL print an error listing valid methods
and continue without changing the active method.

#### Scenario: Teacher method REPL switch updates active method

- **WHEN** the REPL is running with the `teacher` role active and an
  active method of `feynman`
- **AND** the user enters `/method socratic`
- **THEN** the REPL's recorded active method MUST become `socratic`
- **AND** the next agent invocation's input MUST be prefixed with a
  directive mentioning `socratic` and instructing the agent to
  summarize and switch
- **AND** the harness factory MUST NOT be called again as part of the
  switch (agent instance preserved)

#### Scenario: Teacher method REPL prompt prefix reflects active method

- **WHEN** the REPL is running with the `teacher` role active and an
  active method of `feynman`
- **THEN** the prompt prefix for assistant responses MUST be
  `[Teacher:feynman]>` (case-insensitive on the method portion)

#### Scenario: Method REPL switch rejects unknown method

- **WHEN** the REPL is running with the `teacher` role active
- **AND** the user enters `/method bogus`
- **AND** `roles/teacher/skills/bogus.md` does NOT exist
- **THEN** the REPL MUST print an error message listing valid methods
- **AND** the REPL's recorded active method MUST be unchanged
- **AND** the REPL MUST continue without error
