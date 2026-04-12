# Spec Delta: role-registry

## ADDED Requirements

### Requirement: Role Discovery

The system SHALL discover roles as subdirectories of a configured roles root
that contain a `role.yaml` file, excluding directories whose name starts with
an underscore.

#### Scenario: Public role is discovered

- **WHEN** `roles/researcher/role.yaml` exists
- **THEN** `RoleRegistry.discover()` MUST include `"researcher"` in its
  returned list

#### Scenario: Template directory is excluded

- **WHEN** `roles/_template/role.yaml` exists
- **THEN** `RoleRegistry.discover()` MUST NOT include `"_template"`

### Requirement: Persona-Scoped Role Availability

The system SHALL filter discovered roles by the loaded persona's
`disabled_roles` list.

#### Scenario: Disabled role is filtered out

- **WHEN** a persona's `disabled_roles` contains `"coder"`
- **AND** `roles/coder/role.yaml` exists
- **THEN** `RoleRegistry.available_for_persona(persona)` MUST NOT include
  `"coder"`

### Requirement: Role Loading with Persona Overrides

The system SHALL load a role by name and merge persona-specific overrides from
`personas/<persona-name>/roles/<role-name>.yaml` into the base role
definition.

#### Scenario: Base role loads without overrides

- **WHEN** `roles/researcher/role.yaml` defines
  `preferred_tools: ["content_analyzer:search"]`
- **AND** `personas/personal/roles/researcher.yaml` does not exist
- **THEN** `RoleRegistry.load("researcher", personal_persona).preferred_tools`
  MUST equal `["content_analyzer:search"]`

#### Scenario: prompt_append extends the base prompt

- **WHEN** `roles/researcher/prompt.md` contains `"## Role: Researcher\n..."`
- **AND** `personas/personal/roles/researcher.yaml` contains
  `prompt_append: "### Personal Context..."`
- **THEN** the merged `RoleConfig.prompt` MUST end with the append text
- **AND** the merged prompt MUST also contain the base prompt

#### Scenario: additional_preferred_tools extends the list

- **WHEN** base role has `preferred_tools: ["t1"]`
- **AND** override has `additional_preferred_tools: ["t2"]`
- **THEN** merged `preferred_tools` MUST equal `["t1", "t2"]`

#### Scenario: delegation_overrides update individual keys

- **WHEN** base `delegation: { max_concurrent: 3, can_spawn_sub_agents: true }`
- **AND** override `delegation_overrides: { max_concurrent: 2 }`
- **THEN** merged `delegation.max_concurrent` MUST equal `2`
- **AND** merged `delegation.can_spawn_sub_agents` MUST equal `true`

#### Scenario: context_overrides update individual keys

- **WHEN** base `context: { output_format: "structured", save_findings: true }`
- **AND** override `context_overrides: { output_format: "conversational" }`
- **THEN** merged `context.output_format` MUST equal `"conversational"`
- **AND** merged `context.save_findings` MUST equal `true`

#### Scenario: Missing role raises with available list

- **WHEN** `RoleRegistry.load("nonexistent", persona)` is called
- **THEN** `ValueError` MUST be raised
- **AND** the message MUST contain the substring `"Available:"`
