# Session Log — error-resilience

---

## Phase: Plan (2026-05-04)

**Agent**: claude-opus-4-7 (autopilot orchestrator) | **Session**: N/A

### Decisions
1. **Approach A (decorator-based) selected at Gate 1** — `@resilient_http(source=...)` at three call-sites (builder hot path, discovery, future extension probes). Composes inside the existing P4 observability wrapper so retries remain visible to telemetry.
2. **Add tenacity as a regular runtime dep** — not optional. Resilience is cross-cutting; making it conditional creates more confusion than it saves. Aligns with P9 roadmap description and the discovery-question Q1 answer.
3. **Per-source breaker scope** — keys `http_tools:<source>`, `http_tools_discovery:<source>`, `extension:<name>`. Operations within one backend share a breaker. Q2 answer; matches typical backend availability semantics.
4. **HealthStatus dataclass replaces Extension health_check returning bool** — breaking protocol change, all seven stubs updated atomically via a `default_health_status_for_unimplemented(name)` helper. Q3 answer; gives agents enough state to truthfully announce backend unavailability.
5. **In-house CircuitBreaker (~80 LOC) instead of pybreaker** — async-native, namespace matches our key convention exactly, no adapter layer needed.
6. **Tenacity reraise=True so the original exception type is preserved** — existing P3 tests keep their except httpx.HTTPStatusError blocks intact; only the timing of the raise changes.
7. **Sequential tier for execution** — single `wp-main` package; the change is small (about 250 LOC core plus 80 LOC touch sites plus 30 LOC across stubs) and the phases are causally ordered (core then apply then widen protocol).

### Alternatives Considered
- **Approach B (resilient httpx.AsyncClient subclass)**: rejected — magic at call-sites obscures retry behavior during incidents; per-backend scoping is awkward; the wrapper does not help extensions.
- **Approach C (hand-rolled, no tenacity)**: rejected — contradicts the roadmap and the Q1 answer; about 120 LOC net new code versus about 30 LOC of adapter on tenacity.
- **Reuse .agents/skills/parallel-infrastructure/circuit_breaker.py**: rejected — different lifecycle (per-skill-invocation versus long-lived process) and different scoping (package versus HTTP source).

### Trade-offs
- Accepted **one new runtime dep (tenacity)** over **hand-rolled retry** because tenacity does the hard part (composable retry, wait, stop, async support, jitter, exception filtering) correctly and the roadmap explicitly names it.
- Accepted **per-source breaker scope** over **per source times operation** because the Q2 answer and typical backend availability semantics agree; per-operation scope would multiply state without measurable correctness gain.
- Accepted **breaking the Extension protocol** (bool to HealthStatus) over **adding a sibling method** because protocol drift between two health methods is a worse long-term shape than one atomic widen.

### Open Questions
- [ ] Are the default thresholds (5 failures, 30 second cooldown, 3 max_attempts, 0.5 second base delay) right? No production data; will need a follow-up issue at archive time to revisit once P5 and P14 wire real backends.

### Context
Planning P9 of the OpenSpec roadmap (`error-resilience`) under autopilot. P3 (http-tools-layer) is archived, providing the call-sites this change wraps. P4 (observability) is archived, providing the wrapping pattern (`wrap_http_tool`) inside which the new resilience decorator composes. Resilience is a cross-cutting theme — the design intentionally generalizes for P5, P14, and P17 adopters.
