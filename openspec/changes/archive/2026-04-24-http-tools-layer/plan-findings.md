# Plan Findings: http-tools-layer

## Iteration 1 (2026-04-23)

### Parallelizability Summary
- Independent tasks: 0
- Sequential chains: 1 (wp-http-tools-leaves → fork → {composite, policy} → wp-cli → wp-integration)
- Max parallel width: 2 (wp-http-tools-composite ∥ wp-policy at priority 2)
- File overlap conflicts: **1 — see H1 below**

### Findings

| # | Type | Criticality | Description | Proposed Fix |
|---|------|-------------|-------------|--------------|
| H1 | parallelizability | high | The two parallel packages (`wp-http-tools-composite`, `wp-policy`) both logically depend on the public API exported from `src/assistant/http_tools/__init__.py`, which `wp-http-tools-leaves` owns and writes. If `__init__.py` eagerly re-exports `discover_tools` (which lives in composite's `discovery.py`), imports will fail until composite lands. Currently `wp-http-tools-leaves` is sized to own `__init__.py` without this constraint being explicit. | Constrain `__init__.py` to exporting only the leaf symbols (`resolve_auth_header`, `HttpToolRegistry`). Mandate that cli.py and tests import composite symbols via specific modules (`from assistant.http_tools.discovery import discover_tools`), not the package root. Document this as design decision D8 and update tasks.md + work-packages.yaml. |
| H2 | completeness | high | Design.md states Swagger 2.0 documents should be skipped with a warning (not parsed), but `tasks.md` Phase 6 has no test task for that scenario, and `specs/http-tools/spec.md` has no scenario covering it. The feature will silently accept 2.0 docs and misparse them. | Add a scenario under the "HTTP Tool Discovery" requirement for Swagger 2.0 skip-with-warning. Add test task 6.3 asserting the behavior with a 2.0 fixture. Add a `sample_swagger_v2_0.json` fixture. |
| M1 | testability | medium | Spec scenarios say "a warning MUST be logged" (for source-level failures, 2.0 skip, invalid JSON) but the test tasks in Phase 6 don't reference `caplog` or a concrete assertion mechanism. A reader of `tasks.md` has no guidance on how to verify the scenario. | Update tasks.md 6.1 (and the new 6.3) to explicitly note use of `caplog.records` + check for `WARNING` level entries naming the failed source. |
| M2 | clarity | medium | `proposal.md` header mentions "`/help`-based discovery" (inherited from roadmap.md phrasing) but the actual spec behavior prioritizes `GET /openapi.json` with `/help` as a 404-fallback. A reader starting at the proposal expects `/help` to be primary. | Rewrite the relevant proposal.md sentences to clarify OpenAPI at `/openapi.json` is the primary discovery endpoint, with `/help` as a legacy/alternative endpoint path for the same OpenAPI document. |
| L1 | performance/observability | low | No logging task for per-tool-invocation debug output. Services receiving unexpected calls would be hard to diagnose from the assistant side. | Defer — P4 `observability` phase owns structured tracing; P9 `error-resilience` owns retry/circuit-break logging. A plain `logger.debug` call can be added opportunistically during implementation without a task. |

### Decision

Fix H1, H2, M1, M2 in this iteration. L1 is below the medium threshold — logged as future nice-to-have, not gated.
