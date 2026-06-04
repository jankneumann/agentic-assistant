# Spec: patterns-architecture (delta)

## ADDED Requirements

### Requirement: Four-Layer Model

The framework SHALL define a four-layer architectural model consisting of:
(L1) assistant framework, (L2) harness runtime, (L3) patterns, (L4)
transport.

#### Scenario: layers are distinct

WHEN a contributor introduces a new component
THEN the component SHALL belong to exactly one layer
AND its public interface SHALL reference only concepts from its own layer
or the layer immediately above/below it.

#### Scenario: framework owns pattern definitions

WHEN a new pattern is introduced
THEN the pattern's contract (inputs, outputs, semantics) SHALL be defined
at the framework layer (L1/L3)
AND harness-specific implementation details SHALL remain at the harness
layer (L2).

---

### Requirement: Capability Identifier

The framework SHALL define a Capability concept as a named, stable
identifier for each pattern a harness may support.

#### Scenario: capability is extensible

WHEN a downstream proposal introduces a new pattern
THEN it SHALL be assignable a new Capability identifier
AND existing capabilities SHALL remain unchanged
AND no existing harness code SHALL require modification solely to
acknowledge the new capability.

#### Scenario: capabilities are discoverable

WHEN the framework is queried for known capabilities at runtime
THEN it SHALL return the complete set of registered Capability
identifiers.

---

### Requirement: Capability Declaration

A harness SHALL declare a CapabilityInfo for each capability it supports,
specifying at minimum: mode (native, emulated, transport-mediated, or
not_supported), qualitative cost_characteristic (cheap, moderate, or
expensive), and optional notes.

#### Scenario: undeclared capability defaults to not_supported

WHEN a harness does not declare a CapabilityInfo for a given capability
THEN the framework SHALL treat that capability as not_supported on that
harness.

#### Scenario: declaration is per-harness per-capability

WHEN two harnesses declare the same capability
THEN each declaration SHALL be independent
AND each MAY specify a different mode and cost_characteristic.

---

### Requirement: Role Capability Requirements

A RoleConfig SHALL support a required_capabilities field listing the
Capability identifiers the role depends on.

#### Scenario: role with no required_capabilities

WHEN a role has an empty or absent required_capabilities field
THEN the role SHALL bind to any harness regardless of its declared
capabilities
AND backward compatibility with existing roles SHALL be preserved.

#### Scenario: role requires a capability

WHEN a role declares a required_capabilities entry
THEN the role SHALL only bind to a harness that declares that capability
with a mode other than not_supported.

---

### Requirement: Factory Capability Matching

The harness factory SHALL bind a role to a harness only if the harness's
declared capabilities satisfy all entries in the role's
required_capabilities.

#### Scenario: no harness satisfies requirements

WHEN no configured harness declares all capabilities listed in a role's
required_capabilities with a mode other than not_supported
THEN the factory SHALL raise an error
AND the error message SHALL identify which capabilities are unmet
AND which harnesses were evaluated.

#### Scenario: matching algorithm is deferred

WHEN multiple harnesses satisfy a role's required_capabilities
THEN the factory MAY select any qualifying harness
AND the selection algorithm (preference order, tie-breaking, fallback
chains) SHALL be defined by the harness-routing proposal (P11), not by
this specification.

---

### Requirement: Implementation Mode Enumeration

The framework SHALL enumerate the following implementation modes for
capabilities: native, emulated, transport-mediated, and not_supported.

#### Scenario: transport modes are listed

WHEN describing transport-mediated mode
THEN the framework SHALL enumerate A2A, MCP, and HTTP as supported
transport protocols
AND protocol selection mechanics SHALL be deferred to the proposals
that implement each transport (P6, P17).

#### Scenario: mode semantics are distinct

WHEN a harness declares a capability as native
THEN the harness SHALL implement the pattern using its own primitives
without framework-provided fallback logic.

WHEN a harness declares a capability as emulated
THEN the framework SHALL provide a generic implementation that uses
the harness's existing primitives to approximate the pattern.

WHEN a harness declares a capability as transport-mediated
THEN the pattern SHALL execute in a separate agent or service reached
via one of the enumerated transport protocols.
