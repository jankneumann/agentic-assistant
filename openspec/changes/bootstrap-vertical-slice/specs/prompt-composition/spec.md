# Spec Delta: prompt-composition

## ADDED Requirements

### Requirement: Three-Layer System Prompt Composition

The system SHALL compose a system prompt from three ordered layers: the base
system prompt, the persona's prompt augmentation, and the role's prompt — each
separated by a horizontal-rule divider (`---`).

#### Scenario: All three layers are present in order

- **WHEN** `compose_system_prompt(persona, role)` is called with a persona
  whose `prompt_augmentation` is non-empty and a role whose `prompt` is
  non-empty
- **THEN** the returned string MUST contain the base prompt before the persona
  augmentation
- **AND** the persona augmentation MUST appear before the role prompt
- **AND** the layers MUST be separated by `\n\n---\n\n`

#### Scenario: Empty persona augmentation is omitted

- **WHEN** `persona.prompt_augmentation` equals `""`
- **THEN** the returned prompt MUST NOT include a horizontal-rule separator
  where the persona augmentation would have been

#### Scenario: Empty role prompt is omitted

- **WHEN** `role.prompt` equals `""`
- **THEN** the returned prompt MUST NOT contain a trailing separator followed
  by empty content

### Requirement: Active Configuration Summary Appended

The composed prompt SHALL include a final "Active Configuration" section
listing the persona display name, role display name, allowed sub-roles, and
preferred tools.

#### Scenario: Active configuration lists persona, role, and sub-roles

- **WHEN** the role has `delegation.allowed_sub_roles == ["writer", "coder"]`
- **THEN** the composed prompt MUST contain `"**Persona**: <display_name>"`
- **AND** MUST contain `"**Role**: <display_name>"`
- **AND** MUST contain `"**Sub-roles**: writer, coder"`

#### Scenario: No allowed sub-roles renders "none"

- **WHEN** the role has `delegation.allowed_sub_roles == []`
- **THEN** the composed prompt MUST contain `"**Sub-roles**: none"`

#### Scenario: always_plan roles include a planning line

- **WHEN** the role has `planning.always_plan == true`
- **THEN** the composed prompt MUST contain the substring
  `"Planning"` followed by a phrase indicating pre-execution planning
