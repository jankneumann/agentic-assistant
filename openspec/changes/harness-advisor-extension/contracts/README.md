# Contracts: harness-advisor-extension

## Applicability assessment

| Contract sub-type | Applicable? | Rationale |
|-------------------|-------------|-----------|
| OpenAPI | No | No API endpoints introduced or modified. |
| Database | No | No database schemas introduced or modified. |
| Events | No | No events introduced or modified. |
| Type generation | No | Types are internal Python dataclasses (Capability, CapabilityInfo, AdvisorResponse), not generated from schemas. |

P1.7 introduces internal Python types and modifies internal interfaces.
No machine-readable contracts are applicable. The spec delta files serve
as the interface contracts.
