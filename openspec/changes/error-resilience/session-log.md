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

---

## Phase: Plan Iteration 1 (2026-05-04)

**Agent**: claude-opus-4-7 (autopilot self-review) | **Session**: N/A

### Decisions
1. **Add D11 to design.md** — hard protocol break for `health_check` plus a docs/gotchas.md migration note, no deprecation shim. Tasks.md task 4.6 referenced D11 but design.md only had D1 through D10; correcting the inconsistency by writing the actual decision rationale instead of removing the reference.
2. **Add D12 to design.md and a new SHALL requirement to error-resilience spec** — error strings stored on `CircuitBreaker.last_error`, `CircuitBreakerOpenError.last_error_summary`, and `HealthStatus.last_error` MUST pass through `assistant.telemetry.sanitize.sanitize` and be truncated at 200 characters with a literal three-character ellipsis suffix.
3. **Add 429 retry scenario and asyncio-non-blocking-delay scenario** to the resilience decorator requirement — strengthens testability and pins the most common transient code (rate limiting) to a concrete behavioral assertion.

### Alternatives Considered
- **Removing the D11 reference from tasks.md** rather than writing the decision: rejected because the doc-note migration path is a real decision worth recording for future maintainers, not just a tasks.md artifact.
- **Sanitizing only at the telemetry boundary** rather than at the breaker boundary: rejected because `CircuitBreakerOpenError` is an exception that may flow through `repr()` into logs before any telemetry layer sees it; the breaker is the right boundary.

### Trade-offs
- Accepted **a small import dependency from core/resilience.py to telemetry/sanitize.py** over **duplicating sanitize logic** because the existing chain already covers 15 patterns and is the canonical secret-redaction path.

### Open Questions
- [ ] Will the multi-vendor PLAN_REVIEW phase surface additional findings? (Resolved at PLAN_REVIEW; no action here.)

### Context
Self-review pass identified 3 findings at or above the medium threshold: 1 high consistency (D11 reference orphaned), 2 medium (security: error-string sanitization gap; completeness: missing 429 scenario). All three addressed in this iteration. A fourth low-severity finding about the tenacity version pin was dismissed after PyPI confirmed 9.1.4 is current and the `>=9.0,<10.0` pin is correct. `openspec validate --strict` passes after fixes.
