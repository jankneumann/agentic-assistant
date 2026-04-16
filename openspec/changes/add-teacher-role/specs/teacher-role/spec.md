# teacher-role

## ADDED Requirements

### Requirement: Teacher Role Discovery and Loading

The system SHALL expose a public role named `teacher`, discoverable by
`RoleRegistry.discover()` and loadable by
`RoleRegistry.load("teacher", persona)` for any persona whose
`disabled_roles` does not contain `teacher`.

#### Scenario: Teacher role is discoverable

- **WHEN** `roles/teacher/role.yaml` exists
- **AND** `roles/teacher/prompt.md` exists
- **THEN** `RoleRegistry.discover()` MUST include `"teacher"` in its
  returned list

#### Scenario: Teacher declares researcher delegation

- **WHEN** `RoleRegistry.load("teacher", personal_persona)` is called
- **THEN** the returned `RoleConfig.delegation["allowed_sub_roles"]`
  MUST equal `["researcher"]`
- **AND** `RoleConfig.delegation["can_spawn_sub_agents"]` MUST be `True`
- **AND** `RoleConfig.delegation["max_concurrent"]` MUST equal `1`

#### Scenario: Teacher declares knowledge-base tool preferences

- **WHEN** `RoleRegistry.load("teacher", personal_persona)` is called
- **THEN** the returned `RoleConfig.preferred_tools` MUST contain
  `"content_analyzer:search"`
- **AND** it MUST contain `"content_analyzer:knowledge_graph"`

#### Scenario: Teacher skills directory is populated

- **WHEN** `RoleRegistry.load("teacher", personal_persona)` is called
- **THEN** `RoleConfig.skills_dir` MUST resolve to
  `"./roles/teacher/skills"`
- **AND** the directory MUST contain `feynman.md`
- **AND** the directory MUST contain `socratic.md`

### Requirement: First-Turn Method Negotiation

The teacher role SHALL negotiate method selection on its first turn
when no method is supplied via CLI flag or REPL directive: the
first-turn output MUST present the available methods (skill files
under `roles/teacher/skills/`) and ask the user to pick one before
entering any method's loop.

#### Scenario: Teacher offers method choice on first turn

- **WHEN** a session starts with `--role teacher` and no `--method`
- **AND** no `/method` REPL command has been issued
- **THEN** the teacher's first response to any user message MUST name
  the available methods (`feynman`, `socratic`)
- **AND** it MUST ask the user to select one
- **AND** it MUST NOT begin Step 1 of any method before the user
  responds with a selection

#### Scenario: Teacher honors explicit method directive

- **WHEN** a session starts with `--role teacher --method feynman`
- **THEN** the teacher's first response MUST begin Step 1 of the
  Feynman method for the topic given in the user's first message
- **AND** it MUST NOT re-offer a method choice

### Requirement: Skill-Switch Transition Protocol

The teacher role SHALL execute a four-part transition when the active
method changes mid-session (via `/method <name>`): it MUST complete
the current response, produce a ≤3-sentence summary of progress under
the previous method, announce the switch by name, and enter Step 1 of
the new method with the identified remaining gaps as the new loop's
starting focus.

#### Scenario: Skill switch transition preserves state

- **WHEN** the user issues `/method socratic` during an active Feynman
  loop in which they have demonstrated mastery of concept A but not
  concept B
- **THEN** the teacher's next response MUST include a summary sentence
  identifying that concept A is established and concept B remains
- **AND** it MUST include the phrase "Switching to" (case-insensitive)
  naming `socratic`
- **AND** its next step MUST be Step 1 of the Socratic method
  targeting concept B
- **AND** the agent instance MUST NOT be rebuilt (the switch is
  prompt-level, not harness-level)

### Requirement: Feynman Skill Loop Contract

The `feynman.md` skill SHALL define a four-step loop: Step 1 — the
assistant produces a ≤150-word plain-language explanation with one
flagged analogy and prompts the user to explain it back; Step 2 — the
assistant waits for user response; Step 3 — the assistant scores the
user's explanation 1-10, bullets only the gaps, and re-teaches gaps in
≤100 words; Step 4 — loop Step 2-3 until the user scores 9+ without
hints; completion signal — the assistant emits the phrase "You've got
it" followed by a one-sentence transferable definition.

#### Scenario: Feynman skill defines explain-check-reteach loop

- **WHEN** `roles/teacher/skills/feynman.md` is read
- **THEN** it MUST contain a "Step 1" section mentioning a
  ≤150-word plain-language explanation and a flagged analogy
- **AND** it MUST contain a "Step 3" section mentioning a 1-10 score
  and a ≤100-word re-teach of gaps
- **AND** it MUST contain a completion signal with the phrase
  "You've got it"
- **AND** it MUST specify that `content_analyzer:knowledge_graph`
  consultation is permitted before Step 1 only

### Requirement: Socratic Skill Loop Contract

The `socratic.md` skill SHALL define a question-only loop in which the
assistant never states facts, only asks questions that surface the
user's existing model of the topic; the loop continues until the user
can answer their own question about the topic; the completion signal
is the phrase "You're teaching yourself now" followed by a framing
sentence the user could use to open the topic with someone else.

#### Scenario: Socratic skill defines question-only loop

- **WHEN** `roles/teacher/skills/socratic.md` is read
- **THEN** it MUST state that the assistant asks questions and does
  NOT state facts
- **AND** it MUST contain a completion signal with the phrase
  "You're teaching yourself now"
- **AND** it MUST specify that `content_analyzer:knowledge_graph` may
  be consulted silently (not cited to the user) between questions
