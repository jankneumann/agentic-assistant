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

---


## Phase: Plan Iteration 2 (2026-05-04)

**Agent**: claude-opus-4-7 (multi-vendor PLAN_REVIEW remediation) | **Session**: N/A

### Decisions
1. **Non-availability errors do NOT trip the breaker** — D5 expanded. Gemini finding 1 caught a real DoS-by-proxy hazard. With the original spec, one client returning HTTP 401 from bad credentials would have counted toward the breaker threshold, eventually opening the breaker for every other client of the same backend. Fix classifies failures into availability category (retryable codes and exceptions) versus non-availability category (HTTP 401, 403, 422, etc.); only availability failures increment the consecutive-failure counter. New scenario added in error-resilience capability and in http-tools.
2. **Per-attempt visibility uses start_span, not trace_tool_call** — D9 rewritten. Codex finding 1 caught that wrap_http_tool emits exactly one trace span per outer await, so retries inside that await are invisible. The original spec claimed one trace_tool_call per attempt which is unimplementable without rewriting the observability protocol. Fix keeps trace_tool_call as the user-level summary (one per tool invocation) and routes per-attempt and per-state-transition visibility through start_span events named resilience.http_attempt and resilience.breaker_transition. No new ObservabilityProvider Protocol method.
3. **Decorator argument is breaker_key, not source** — codex finding 3 identified that the spec said the breaker registry key was prefixed with http_tools but the call-site used the source argument, which would have created the key without the prefix. Fix renames the argument to breaker_key and requires call sites to construct the canonical fully-namespaced string explicitly. No implicit prefixing inside the decorator.
4. **Discovery wrap site is discovery.py at function _fetch_openapi, not openapi.py** — codex finding 2 caught that the actual network fetch lives in discovery.py at line 27, while openapi.py only handles parsing. The work-packages.yaml write_allow scope was missing discovery.py. Fix updates proposal, spec, tasks, and work-packages to name the correct file and scope it for write access.
5. **Half-open admits exactly one probe** — D13 added. Codex finding 4 plus gemini finding 3 (consensus). The original spec had a race where multiple concurrent tasks could each observe state open and now greater than next_probe_at, each transition the breaker to half_open, and each issue a probe. Fix tracks an explicit in-flight-probe boolean inside the breaker; concurrent callers arriving while a probe is in flight raise CircuitBreakerOpenError instead of issuing a second probe. New scenario added.
6. **Default retryable_exceptions includes ConnectTimeout and WriteTimeout** — D5 expanded. Codex finding 5 plus gemini finding 2 (consensus). The original list omitted these timeout subclasses. Fix adds both, with explicit trade-off documentation that WriteTimeout retries on non-idempotent POST or PUT can cause double-create (bounded by max_attempts=3; method-aware retry policies deferred as future work).
7. **Threshold-opening scenario requires sanitized last_error** — codex finding 6 noted that the scenario said last_error MUST equal the raw string representation of the error, but the sanitization requirement said it must be sanitized first. Fix has the scenario say the sanitized and truncated string representation.
8. **Runtime conformance check** — D11 expanded. Codex finding 7 noted that runtime_checkable Protocol does not validate return types at runtime; core.persona returns list of Any for dynamically-loaded extensions. A private extension could keep returning bool and only fail later. Fix requires both static (mypy) and runtime guard at the first health-check consumption point in the persona registry; new task 3.5 implements it; new scenario added to extension-registry.
9. **Multi-byte truncation uses Python str slicing** — D14 added. Gemini finding 4: spec did not specify truncation strategy. Fix documents that Python string slicing on str is character-aware; no risk of splitting multi-byte UTF-8 sequences.
10. **Retry-After header support deferred to future work** — D15 added. Gemini finding 5: respecting Retry-After requires plumbing the response object through the tenacity wait clauses, expanding v1 scope. Fix documents the deferral with future shape (a respect_retry_after boolean field defaulting to False so the v1 default is preserved unless callers opt in).

### Alternatives Considered
- Per-attempt trace_tool_call (changing the observability spec): rejected because it breaks the one-trace-per-tool-invocation invariant other consumers rely on, and inflates cost-attribution.
- Implicit namespace prefixing in the decorator (a source argument with auto-prefix): rejected because then the decorator would need a kind parameter to distinguish between three namespaces. Explicit breaker_key is one less concept and one less convention to remember.
- WriteTimeout not retried by default (only ConnectTimeout): rejected because the agent workload is read-heavy, the bound is max_attempts=3, and per-call-site override is available for non-idempotent operations.
- Implementing Retry-After in v1: rejected because of plumbing cost versus v1-shape goals.

### Trade-offs
- Accepted a more complex decorator API (caller constructs canonical breaker key) over implicit prefixing because explicitness avoids the silent class of bugs codex finding 3 caught.
- Accepted bounded WriteTimeout retry hazard over method-aware retry policies in v1 because the bounded blast radius (max 3 retries, agent-typical workload) is small and method-awareness adds significant complexity.
- Accepted runtime TypeError on legacy bool-returning extensions over gradual deprecation because a clear early failure with a migration message is operationally better than silent degradation.

### Open Questions
- [ ] Are the default thresholds (5 failures, 30 second cooldown, 3 max_attempts, 0.5 second base delay) right under real backends? Carried from iteration 1; resolved post-archive once P5 and P14 wire real probes.

### Context
Multi-vendor PLAN_REVIEW (claude excluded; codex returned 7 findings, gemini returned 5). Two findings reached cross-vendor consensus: half-open concurrency, and WriteTimeout missing from default retryable. All 7 codex findings plus 1 high-severity gemini finding addressed in this iteration. Two low-severity findings (multi-byte truncation, Retry-After header) accepted with documented future-work rationale. openspec validate --strict still passes after fixes.
