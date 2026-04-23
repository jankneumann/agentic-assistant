# Change Context: http-tools-layer

## Requirement Traceability Matrix

Grouped by Requirement from `specs/http-tools/spec.md`; each row lists
scenario count, contract ref, design decisions, test file, impl file,
and evidence status.

| # | Requirement | Scenarios | Contract Ref | Design | Test File | Impl File | Files Changed | Evidence |
|---|-------------|-----------|--------------|--------|-----------|-----------|---------------|----------|
| 1 | HTTP Tool Discovery | 6 | `contracts/fixtures/sample_openapi_v3_1.json`, `malformed_openapi.json`, `sample_swagger_v2_0.json` | D4, D10 | `tests/http_tools/test_discovery.py` | `src/assistant/http_tools/discovery.py` | --- | pending |
| 2 | OpenAPI Operation Parsing | 5 | `contracts/fixtures/sample_openapi_v3_{0,1}.json`, `cyclic_ref_openapi.json`, `external_ref_openapi.json` | D5, D10 | `tests/http_tools/test_openapi.py` | `src/assistant/http_tools/openapi.py` | --- | pending |
| 3 | Tool Builder Generates Typed StructuredTool | 10 | --- | D1, D2, D6 | `tests/http_tools/test_builder.py` | `src/assistant/http_tools/builder.py` | --- | pending |
| 4 | HTTP Client Security Posture | 4 | --- | D9 | `tests/http_tools/test_discovery.py`, `test_builder.py` | `src/assistant/http_tools/discovery.py`, `builder.py` | --- | pending |
| 5 | Auth Header Resolution | 4 | --- | D11 | `tests/http_tools/test_auth.py` | `src/assistant/http_tools/auth.py` | --- | pending |
| 6 | HttpToolRegistry API | 2 | --- | D3, D7 | `tests/http_tools/test_registry.py` | `src/assistant/http_tools/registry.py` | --- | pending |
| 7 | CLI Startup Integration | 2 | --- | D2, D8 | `tests/test_cli.py` | `src/assistant/cli.py` | --- | pending |
| 8 | `--list-tools` CLI Subcommand | 3 | --- | D8 | `tests/test_cli.py` | `src/assistant/cli.py` | --- | pending |
| 9 | tool-policy: DefaultToolPolicy extension (3 MODIFIED scenarios) | 3 | --- | --- | `tests/core/capabilities/test_tool_policy_http.py` | `src/assistant/core/capabilities/tools.py` | --- | pending |
| 10 | tool-policy: Tool Manifest Export (2 scenarios) | 2 | --- | --- | `tests/core/capabilities/test_tool_policy.py` | `src/assistant/core/capabilities/tools.py` | --- | pending |
| 11 | cli-interface: List Tools Prints (3 scenarios) | 3 | --- | --- | `tests/test_cli.py` | `src/assistant/cli.py` | --- | pending |
| 12 | cli-interface: CLI Entry Point — list-tools short-circuits REPL | 1 | --- | --- | `tests/test_cli.py` | `src/assistant/cli.py` | --- | pending |
| 13 | Persona auth_header schema evolution (D11) | — | --- | D11 | `tests/core/test_persona_auth_header.py` | `src/assistant/core/persona.py` | --- | pending |

## Design Decision Trace

| Decision | Validates | Test Coverage |
|----------|-----------|---------------|
| D1 | Runtime `pydantic.create_model` for args_schema | test_builder.py |
| D2 | Single shared `async with httpx.AsyncClient()` | test_cli.py, test_discovery.py |
| D3 | `{source}:{op_id}` registry keys | test_registry.py |
| D4 | Discovery fails skip; invocation errors raise | test_discovery.py, test_builder.py |
| D5 | operationId slug fallback | test_openapi.py |
| D6 | Tool description from summary → description → synthesized | test_builder.py |
| D7 | `HttpToolRegistry` concrete class | test_registry.py |
| D8 | Minimal `__init__.py` exports (leaf symbols only) | import-time (verified by package boundary tests) |
| D9 | HTTP client security posture (timeout, TLS, 10 MiB streaming cap, no redirects, credential redaction) | test_discovery.py, test_builder.py |
| D10 | OpenAPI `$ref` resolution (intra/external/cyclic) | test_openapi.py |
| D11 | Persona auth_header schema evolution | test_persona_auth_header.py, test_auth.py |

## Coverage Summary

- **Total requirements**: 13 (http-tools 8 + tool-policy 2 + cli-interface 2 + persona schema 1)
- **Total scenarios**: ~45
- **Implemented**: 0 / 13
- **Tests written**: 0 / 13
- **Tests passing**: 0 / 13

Updated per work-package completion.

## Evidence

Populated at end of implementation from `git diff main..HEAD`.
