# Independent Implementation Review — error-resilience (P9)

You are reviewing the implementation of OpenSpec change `error-resilience`. The author of the implementation is a separate Claude agent. Find genuine bugs, edge cases, or spec-vs-implementation mismatches — do not rubber-stamp.

## Read these artifacts (relative to repo root)

**The new code itself**:
- `src/assistant/core/resilience.py` — entire module (~350 LOC)
- `src/assistant/core/persona.py` lines 146-260 — runtime conformance guard
- `src/assistant/extensions/base.py` — Extension Protocol with widened return type
- `src/assistant/extensions/_stub.py` — stub implementation
- `src/assistant/http_tools/builder.py` — `_build_tool` resilient_http wrap site (lines 269-285)
- `src/assistant/http_tools/discovery.py` — `_fetch_one_path` + `_fetch_openapi` refactor

**Tests covering the new code**:
- `tests/core/test_resilience.py`
- `tests/core/test_resilience_decorator.py`
- `tests/http_tools/test_builder_resilience.py`
- `tests/http_tools/test_openapi_discovery_resilience.py`
- `tests/extensions/test_health_status.py`

**Specs the implementation must satisfy**:
- `openspec/changes/error-resilience/specs/error-resilience/spec.md`
- `openspec/changes/error-resilience/specs/http-tools/spec.md`
- `openspec/changes/error-resilience/specs/extension-registry/spec.md`
- `openspec/changes/error-resilience/specs/observability/spec.md`
- `openspec/changes/error-resilience/design.md` — 15 decisions (D1-D15)

## Review focus areas

1. **Spec compliance**: For each scenario in the four spec files, can you find a test that asserts it? Are any scenarios untested? Are tests asserting against the spec or against the implementation (those are different)?

2. **Concurrency correctness in `CircuitBreaker.acquire_admission`**: the in-flight-probe boolean is set under the lock and cleared in a `try/finally`. Are there any reachable paths where the `finally` does not run? What happens if `record_success` and `record_failure` are both called inside the same `acquire_admission` block?

3. **Tenacity composition in `_run_with_retry`**: the inner `try/except` captures `last_error_type` for the next attempt's span attribute, then re-raises. Tenacity's retry predicate then runs against the outcome. Does the predicate correctly handle the case where the wrapped coroutine raises `CircuitBreakerOpenError` from a nested call (e.g., a discovery probe that itself uses an http_tools breaker)? The test_resilience_decorator.py does not cover this nested case.

4. **Discovery refactor edge cases**: `_fetch_one_path` raises `_OpenAPINotAtPath` for 4xx and `httpx.HTTPStatusError` for 5xx. The retry policy retries the latter. What happens at the cooldown boundary if `/openapi.json` opens the breaker, then `/help` tries — are they sharing one breaker (`http_tools_discovery:<source>`) or two? Should they share?

5. **Sanitize+truncate ordering**: `_sanitize_and_truncate` runs sanitize first, then truncates. If sanitize replaces a long secret with a short marker and the result is then truncated, secrets might re-appear from the not-yet-redacted tail. Is the test coverage strong enough to catch this if the regex order changes?

6. **`_install_health_check_conformance_guard` self-removal**: the guard replaces `ext.health_check`, then on success self-removes via `ext.health_check = original`. If the extension is shared across personas and probed concurrently from two of them, can this produce a race where one caller sees the guard removed mid-call?

7. **Default policy values**: are the defaults (5 failures, 30s cooldown, 3 attempts, 0.5s base, 0.25 jitter) reasonable for the agent workload? The proposal flagged them as Open Question.

8. **Builder composition**: at builder.py line 274, the resilient decorator is applied directly to `_coroutine` before `_async_wrapper`. Is the composition order observable to the test that verifies tool tracing? Does `wrap_http_tool`'s tracing see one call per tool invocation (correct per D9) or per attempt (would violate the observability spec)?

9. **TypeError from runtime guard**: the conformance guard raises `TypeError` if `health_check` returns the wrong type. Could this be caught and silenced anywhere upstream (e.g., by `try/except Exception` in a caller), defeating the migration error?

## Output format

Output **valid JSON only** — no Markdown wrapper, no preamble. Conform to:

```json
{
  "review_type": "implementation",
  "target": "error-resilience",
  "reviewer_vendor": "<your vendor identifier>",
  "findings": [
    {
      "id": 1,
      "type": "spec_gap | contract_mismatch | architecture | security | performance | style | correctness | observability | compatibility | resilience",
      "criticality": "critical | high | medium | low",
      "description": "What is the issue, with file:line reference",
      "resolution": "What specific change would fix it",
      "disposition": "fix | regenerate | accept | escalate"
    }
  ]
}
```

Severity guidance:
- **critical**: blocks merge — provable bug, security regression, or spec violation that tests do not catch
- **high**: must fix — real bug under realistic conditions, even if uncommon; ambiguity that has multiple valid interpretations
- **medium**: should fix — incomplete edge-case coverage; missing test; weak rationale
- **low**: polish — wording, ordering

If you find zero issues at criticality medium or above, return an empty `findings` array. Do not invent issues.

Be specific. "Add more tests" is not a finding. "tests/core/test_resilience.py does not assert that record_failure of a non-availability error keeps state closed" is a finding.
