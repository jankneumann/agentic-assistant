# Spec: harness-adapter (delta)

## MODIFIED Requirements

### Requirement: Capability Declaration Classvar

The HarnessAdapter ABC SHALL remain unchanged (no new abstract methods).
Each HarnessAdapter subclass SHALL declare a `capabilities` class
variable mapping Capability identifiers to CapabilityInfo declarations.

#### Scenario: adapter declares supported capabilities

WHEN a HarnessAdapter subclass supports one or more capabilities
THEN the subclass SHALL include a `capabilities` class variable
containing a mapping from each supported Capability to its
CapabilityInfo.

#### Scenario: undeclared capability defaults to not_supported

WHEN the factory queries an adapter for a Capability not present in
its `capabilities` mapping
THEN the result SHALL be equivalent to a CapabilityInfo with mode
not_supported (per P1.6 D3).

---

### Requirement: Deep Agents ADVISE Declaration

The DeepAgentsAdapter SHALL declare Capability.ADVISE with mode native
and cost_characteristic cheap.

#### Scenario: Deep Agents supports ADVISE

WHEN the factory inspects DeepAgentsAdapter capabilities
THEN ADVISE SHALL be present
AND mode SHALL be native
AND cost_characteristic SHALL be cheap.

---

### Requirement: MS Agent Framework ADVISE Declaration

The MSAgentFrameworkAdapter SHALL declare Capability.ADVISE with mode
emulated and cost_characteristic expensive.

#### Scenario: MS AF supports ADVISE via emulation

WHEN the factory inspects MSAgentFrameworkAdapter capabilities
THEN ADVISE SHALL be present
AND mode SHALL be emulated
AND cost_characteristic SHALL be expensive.

---

### Requirement: Factory Capability Match

The harness factory SHALL verify that the bound harness declares all
capabilities listed in the role's required_capabilities before creating
an agent.

#### Scenario: all capabilities satisfied

WHEN a role declares required_capabilities and the bound harness
declares all of them with a mode other than not_supported
THEN the factory SHALL proceed with agent creation.

#### Scenario: capability not satisfied

WHEN a role declares a required_capability that the bound harness does
not support (mode is not_supported or capability is absent)
THEN the factory SHALL raise an error
AND the error message SHALL identify the unmet capability and the
harness that was evaluated.
