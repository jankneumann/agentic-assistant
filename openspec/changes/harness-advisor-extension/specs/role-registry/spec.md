# Spec: role-registry (delta)

## MODIFIED Requirements

### Requirement: Role Required Capabilities Field

The RoleConfig SHALL support an optional required_capabilities field
listing Capability identifiers the role depends on.

#### Scenario: role with required_capabilities

WHEN a role YAML file includes a required_capabilities list
THEN the RoleConfig loader SHALL parse each entry as a Capability
identifier
AND store the list on the loaded RoleConfig instance.

#### Scenario: role without required_capabilities

WHEN a role YAML file omits required_capabilities or sets it to an
empty list
THEN the RoleConfig SHALL have an empty required_capabilities list
AND the role SHALL bind to any harness regardless of capabilities
(backward-compatible).

---

### Requirement: Role Executor Model Override

The RoleConfig SHALL support an optional executor_model field that
overrides the persona-level harness model for agent creation.

#### Scenario: executor_model present

WHEN a role YAML file includes executor_model
THEN the harness adapter SHALL use that model instead of
persona.harnesses.<name>.model when creating the agent.

#### Scenario: executor_model absent

WHEN a role YAML file omits executor_model
THEN the harness adapter SHALL fall back to
persona.harnesses.<name>.model as before (backward-compatible).

#### Scenario: persona override merges executor_model

WHEN a persona role override sets executor_model
THEN the override value SHALL replace the base role value entirely
(shallow merge, not append).

---

### Requirement: Role Advisor Configuration Block

The RoleConfig SHALL support an optional advisor block with keys: model
(string, default claude-opus-4-6), trigger (string, default on_demand),
max_calls_per_task (integer, default 3), budget_tokens (integer, default
1800).

#### Scenario: advisor block present

WHEN a role YAML file includes an advisor block
THEN the RoleConfig loader SHALL parse all keys with their defaults
AND store the parsed config on the RoleConfig instance.

#### Scenario: advisor block absent

WHEN a role YAML file omits the advisor block
THEN the RoleConfig SHALL have no advisor configuration
AND no AdvisorTool SHALL be created for the role.

#### Scenario: invalid advisor block

WHEN a role YAML file includes an advisor block with unrecognized keys
or invalid types
THEN the RoleConfig loader SHALL raise a validation error identifying
the malformed field.
