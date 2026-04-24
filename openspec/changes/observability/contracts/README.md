# Contracts — observability

This change does **not** introduce any machine-readable contracts. The
following contract sub-types were evaluated; none apply:

| Sub-type | Applicable? | Rationale |
|----------|:-----------:|-----------|
| OpenAPI  | No | This change adds no HTTP endpoints. The Langfuse backend API is consumed via the `langfuse` SDK, which owns its own schema. |
| Database | No | This change adds no tables. Langfuse's internal schema is managed by the Langfuse docker image's own migrations. |
| Events   | No | This change does not publish or subscribe to application-level events. Spans are emitted to an external backend (Langfuse) via the vendor SDK, not to an event bus in this repo. |
| Type stubs | No | No shared types are generated cross-service. |

The `ObservabilityProvider` Protocol in `src/assistant/telemetry/providers/base.py`
functions as an in-process contract between the telemetry module and its
consumers (harness, delegation, memory, tool wrappers). It is versioned via
the normal OpenSpec capability-spec flow rather than as a machine-readable
contract artifact, because its consumers all live in the same Python package
and no cross-service or cross-language codegen is needed.
