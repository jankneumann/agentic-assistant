# Contracts — error-resilience

No contract sub-types apply to this change. Each was evaluated:

- **OpenAPI contracts**: not applicable — this change adds no HTTP endpoints. It modifies how an existing HTTP client (http_tools) handles transient failures, but does not introduce any new request/response contracts.
- **Database contracts**: not applicable — no schema changes; the resilience module is purely in-memory state.
- **Event contracts**: not applicable — no events are emitted across process boundaries. Circuit-breaker state transitions are recorded inside the existing observability span tree (see `specs/observability/spec.md` delta), but those spans are not a versioned event contract — they're internal telemetry.
- **Type generation stubs**: not applicable — no contracts above means no generated stubs.

The behavioral contracts that matter for this change live in the spec deltas under `../specs/` — they govern Python types and decorator semantics rather than wire-level interfaces.
