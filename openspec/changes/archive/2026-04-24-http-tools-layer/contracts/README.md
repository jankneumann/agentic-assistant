# Contracts: http-tools-layer

This change introduces HTTP tool discovery via the OpenAPI 3.x wire
format. Contracts here describe the external-facing shape that any
service advertising tools to the assistant MUST conform to.

## Contents

- `openapi/service-manifest.schema.yaml` — the minimal OpenAPI 3.1
  profile this change consumes at discovery time. Services that wish
  to advertise tools to the assistant SHOULD conform to this profile.
- `fixtures/` — sample OpenAPI documents used by the integration
  tests. These double as canonical examples for service authors.

## Evaluated Sub-Types

| Sub-type | Status | Reason |
|----------|--------|--------|
| OpenAPI | **Present** | Defines the discovery wire format. |
| Database | N/A | No schema changes. |
| Event | N/A | No events published or consumed. |
| Type Generation | N/A | Pydantic models generated at runtime per D1 — no static codegen. |

## Service Author Expectations

A service that wants the assistant to discover its tools SHOULD:

1. Expose `GET /openapi.json` returning an OpenAPI 3.0 or 3.1 document
   (fallback: `GET /help`).
2. Provide a stable `operationId` for every operation (recommended but
   not required — the client synthesizes slugs when absent).
3. Provide a `summary` or `description` per operation — the assistant
   uses this as the tool description for LLM dispatch.
4. Advertise `requestBody` + `parameters` schemas as JSON Schema (this
   is what the assistant uses to build the Pydantic `args_schema`).
