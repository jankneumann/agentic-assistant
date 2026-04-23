# Session Log: http-tools-layer

---

## Phase: Plan (2026-04-23)

**Agent**: claude-code (Opus 4.7, 1M context) | **Session**: autopilot-run-1

### Decisions

1. Approach A — dedicated `http_tools/` module with the registry injected into `CapabilityResolver`. Minimal surface; defers any `ToolSource` abstraction to P17 when a second concrete source exists. Matches the three roadmap acceptance outcomes literally.
2. Discovery wire format — OpenAPI 3.x. Industry standard; richer schemas than a bespoke manifest; services can document with existing tooling. Fallback from the `/openapi.json` endpoint to `/help` for convenience.
3. Integration shape — extend the existing `DefaultToolPolicy` rather than introduce a new policy or source abstraction. The registry goes on the constructor; `authorized_tools` merges and filters.
4. Mock server — pytest-httpserver. Real HTTP on a random port exercises the full httpx stack. Added as a dev dependency.
5. Auth scope — static bearer and api-key only. OAuth / refresh deferred to P5 (ms-graph-extension) and P10 (extension-lifecycle). `resolve_auth_header` is a pure function.
6. Runtime Pydantic model generation via `pydantic.create_model()` — D1 in design. Personas can declare arbitrary `tool_sources`, so pre-generated typed stubs would break clone-and-run. Runtime cost is a one-time startup hit measured in milliseconds per operation.
7. Single shared `httpx.AsyncClient` per process — D2 in design. Connection pooling across sources is more efficient than per-tool clients; lifecycle managed via `weakref.finalize`.
8. Registry keys formatted as source colon operation — D3 in design. Namespaces across services; keeps `role.preferred_tools` expressive; aligns with the already-forward-declared `content_analyzer:search` preferences in the archived `add-teacher-role` change.
9. Discovery failures skip the source; per-invocation failures raise — D4 in design. A half-working assistant beats a non-starting one; invocation errors must bubble so the LLM does not fall back to a misleading empty answer.
10. Five work packages across the coordinated tier — `wp-http-tools-leaves` at priority 1; `wp-http-tools-composite` and `wp-policy` in parallel at priority 2; `wp-cli` at priority 3; `wp-integration` at priority 4. Non-overlapping `write_allow` scopes.

### Alternatives Considered

- Approach B (a `ToolSource` Protocol with `HttpToolSource` as first implementation): rejected as premature abstraction. Only one concrete source in sight for P3; generalization should wait until P17 introduces MCP as a second source.
- Approach C (discovery owned by `DefaultToolPolicy`, lazy and cached): rejected because it contradicts the explicit roadmap acceptance outcome that the CLI calls discovery at startup. Fusing discovery into the policy also harms testability.
- Custom JSON manifest instead of OpenAPI: rejected. OpenAPI parameters and requestBody schemas map more cleanly to Pydantic; services can be auto-introspected with existing tooling.
- Pre-generated Pydantic models via `datamodel-code-generator`: rejected. Requires a build step per persona; breaks clone-and-run for personas that configure new `tool_sources`.
- respx as the mock layer: rejected in favor of pytest-httpserver because real-socket tests catch more regressions.
- Full credential provider abstraction: rejected as over-building for P3 scope; bearer and api-key suffice.

### Trade-offs

- Accepted runtime reflection cost at CLI startup over static codegen because personas are user-configured and the cost amortizes across the entire session.
- Accepted a MODIFIED tool-policy spec coupling over introducing a new policy type because the existing `DefaultToolPolicy` is already the right seam; a second policy would fragment the filtering path.
- Accepted a slightly chunky `wp-http-tools-leaves` package (three leaf modules plus tests, roughly 320 LOC) over finer-grained splitting to keep the total count at four implementation packages plus one integration package, within the complexity-gate default.
- Accepted silent skip-on-failure for per-source discovery errors over fail-fast to keep the assistant usable during partial service outages; this trades some discoverability — users must read logs — for availability.

### Open Questions

- [ ] Does any persona already configure `tool_sources` with a live base_url that we should smoke-test against? Task 11.4 is manual; the pytest suite covers the mock path.
- [ ] When P9 `error-resilience` lands, will the retry decorator wrap `discover_tools` or the tool coroutines? Design decision for P9; not blocking here.
- [ ] Is `docs/architecture-analysis/*.json` worth generating now, or defer until a phase that actually needs the component graph? The `refresh-architecture` skill exists but lacks a `make architecture` driver in this repo.

### Context

Plan authored via `/autopilot http-tools-layer` — the PLAN phase of the autopilot state machine. The coordinator is available at `coord.rotkohl.ai` over HTTP transport; tier selection yielded coordinated because all capabilities are present and three vendor CLIs are available for downstream review convergence. The dependency `capability-protocols` was archived 2026-04-20 and provides the `ToolPolicy` protocol that this change's registry plugs into.

---

## Phase: Plan Iteration 1 (2026-04-23)

**Agent**: claude-code (Opus 4.7, 1M context) | **Session**: autopilot-run-1

### Decisions

1. **D8 added to design — minimal `http_tools/__init__.py`.** `__init__.py` re-exports only the leaf symbols (`AuthHeaderConfig`, `resolve_auth_header`, `HttpToolRegistry`). Consumers import composite symbols via their specific module path. Fixes a real problem the DAG had: under coordinated tier, `wp-http-tools-leaves` merges before `wp-http-tools-composite`, and an eager `from .discovery import discover_tools` in `__init__.py` would break package imports at every intermediate state.
2. Work-packages `deny` scope entry added to `wp-http-tools-composite` explicitly forbidding writes to `__init__.py`. The lock rationale now cites D8 so reviewers do not re-open the question.
3. New spec scenario — Swagger 2.0 skip-with-warning. Design already said this was the intended behavior; it was unspecified. Added under the HTTP Tool Discovery requirement and matching tasks 1.4 (fixture) and 6.3 (test).
4. The `caplog` assertion pattern is now explicitly required in task 6.1 and 6.3. Implementors have a concrete pytest mechanism to verify the warning-log scenarios.
5. Proposal Why section reworded to state OpenAPI at `{base_url}/openapi.json` is the primary discovery endpoint, with `{base_url}/help` as a 404 fallback. Removes the ambiguity introduced by the roadmap shorthand that referred to help-based discovery as primary.

### Alternatives Considered

- **Move `__init__.py` ownership to `wp-integration` (final package)**: rejected because leaves would have no importable package surface, breaking its own tests.
- **Delete `__init__.py` re-exports entirely; require fully-qualified imports everywhere**: rejected because `HttpToolRegistry` is widely consumed and benefits from the shorter path. Compromise is the minimal re-export in D8.
- **Pre-seed `__init__.py` with `from .discovery import discover_tools  # noqa: lazy`**: rejected — lazy-import gymnastics are fragile and the naïve reader assumes the symbol is always importable.

### Trade-offs

- Accepted a small import-style asymmetry (leaf symbols via package root, composite symbols via module) for a strict DAG-import invariant: `python -c "import assistant.http_tools"` never fails between merge points.
- Accepted an extra fixture + test task (roughly 50 LOC) to keep the Swagger 2.0 behavior specified rather than silently correct.

### Open Questions

- [ ] Should `__init__.py` eventually re-export `discover_tools` once the composite package lands? Proposed: yes, as an additive follow-up after P3 archives. Tracked in D8 consequence section.

### Context

Iteration 1 addressed 1 high-parallelizability finding (H1), 1 high-completeness finding (H2), and 2 medium findings (M1 clarity, M2 testability). One low finding (L1 — per-invocation debug logging) deferred to P4 `observability`. Validation green. Ready for vendor review dispatch.
