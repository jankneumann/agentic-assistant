# Independent Plan Review — error-resilience (P9 of agentic-assistant roadmap)

You are reviewing an OpenSpec plan proposal as an **independent reviewer**. The author of the plan is a separate Claude agent. Your job is to find genuine issues — not to rubber-stamp.

## Read these artifacts first

All paths are relative to the repo root (`./`):

- `openspec/changes/error-resilience/proposal.md` — what + why + chosen approach
- `openspec/changes/error-resilience/design.md` — 12 decisions (D1–D12) with rationale
- `openspec/changes/error-resilience/tasks.md` — 21 tasks across 4 phases (TDD-ordered)
- `openspec/changes/error-resilience/specs/error-resilience/spec.md` — new capability
- `openspec/changes/error-resilience/specs/extension-registry/spec.md` — protocol widen
- `openspec/changes/error-resilience/specs/http-tools/spec.md` — apply at builder + discovery
- `openspec/changes/error-resilience/specs/observability/spec.md` — composition rule
- `openspec/changes/error-resilience/work-packages.yaml` — sequential single-package execution

## Codebase context (also relative to repo root)

- `src/assistant/http_tools/builder.py` — current per-tool invocation (the hot path being wrapped)
- `src/assistant/http_tools/discovery.py` — current discovery (already graceful per P3 D4)
- `src/assistant/extensions/base.py` — Extension Protocol (`health_check() -> bool` today)
- `src/assistant/telemetry/sanitize.py` — secret-redaction chain referenced by D12
- `src/assistant/telemetry/tool_wrap.py` — `wrap_http_tool` observability decorator (P4)
- `pyproject.toml` — dep file (currently no tenacity)
- `openspec/roadmap.md` — phase sequence (P9 row, "Resilience" cross-cutting theme)

## Review dimensions (apply all of them)

1. **Specification completeness** — Are all retry / breaker / health-status behaviors fully captured? Any failure modes (timeout vs connection vs DNS vs HTTP-status) without an explicit scenario? Any state-machine transition unspecified?
2. **Contract consistency** — Does the spec match what `tasks.md` instructs the implementer to build? Do `design.md` decisions contradict any spec scenario? Is the import direction (core → telemetry/sanitize) safe from cycles?
3. **Architecture alignment** — Is `core/resilience.py` the right home? Is the decorator-vs-client-wrapper choice (Approach A) sound given the actual call sites at `builder.py:233` and `discovery.py`?
4. **Security** — Are sanitization rules sufficient to prevent token / response-body leakage from `last_error` strings? Are there auth headers in `builder.py` that could appear in error messages?
5. **Performance** — Is the `asyncio.Lock` per breaker a contention risk? Does the worst-case retry chain (~2.5s by stated math) match the configured policy? What about the half-open probe race when many tasks see the open breaker simultaneously?
6. **Resilience semantics** — Is there a missing scenario for connection-pool exhaustion? For `httpx.WriteTimeout` (not in retryable_exceptions today)? For when the same backend hits 429 and 503 alternately?
7. **Compatibility** — The `Extension` protocol change (`bool → HealthStatus`) is a hard break. Is the migration recipe in `docs/gotchas.md` sufficient? Will mypy actually catch the break in test code, not just src code?
8. **Observability** — Does the composition order ("resilience inside wrap_http_tool") emit one span per attempt? Will the open-breaker span have useful attributes (breaker_key, opened_at)?
9. **Testability** — Are the scenarios verifiable without flakiness (e.g., the asyncio non-blocking-delay scenario — how is it asserted)? Does the truncation scenario (length 200 with `...` suffix) handle multi-byte chars correctly?
10. **Work package validity** — `wp-main` has tier `tier_b`. Is that correct verification level? Are write_allow paths complete (e.g., does the change touch `pyproject.toml` for tenacity? Yes — listed)?

## Output format

Output **valid JSON only** — no Markdown wrapper, no preamble, no commentary. Conform to this schema:

```json
{
  "review_type": "plan",
  "target": "error-resilience",
  "reviewer_vendor": "<your vendor identifier>",
  "findings": [
    {
      "id": 1,
      "type": "spec_gap | contract_mismatch | architecture | security | performance | style | correctness | observability | compatibility | resilience",
      "criticality": "critical | high | medium | low",
      "description": "What is the issue, with file:line or spec section reference",
      "resolution": "What specific change would fix it",
      "disposition": "fix | regenerate | accept | escalate"
    }
  ]
}
```

## Severity guidance

- **critical** — blocks implementation: missing requirement that would lead to wrong code; security regression
- **high** — must fix before implementation: ambiguity that has multiple valid interpretations; testability gap that would let a buggy implementation pass review
- **medium** — should fix: incomplete edge-case coverage; missing scenario; weak rationale
- **low** — polish: wording, ordering, docs

If you find **zero issues** at criticality ≥ medium, return an empty `findings` array. Do not invent issues.

If a finding requires a human decision (scope question, trade-off the author cannot make alone), use `disposition: "escalate"`.

Be specific. "Add more tests" is not a finding. "Add a scenario asserting that `httpx.WriteTimeout` is NOT retried under default policy" is a finding.
