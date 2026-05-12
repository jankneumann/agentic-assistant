# IMPL_REVIEW round 4 — ms-graph-extension (P5)

You are doing the final convergence review of OpenSpec change `ms-graph-extension`. This is round 4, dispatched after the documented `max_rounds=3` because round 3 surfaced a new regression that has now been addressed in iteration 5 (commit `7801948`).

## Round 4 scope

**Single question**: Has the round-3 regression been correctly fixed without introducing new bugs?

The round-3 finding was:
- Wrapping `httpx.TransportError` → `GraphAPIError` before `@resilient_http` saw it broke the P9 retry classifier (which matches by exception type and `status_code` — neither matched after wrapping).

The iteration-5 (commit `7801948`) fix applies **Option A**:

1. **Inside `_send_with_auth_retry`** and **`_get_bytes_inner`**: emit observability span on `httpx.TransportError`, then re-raise the **raw** httpx exception (no wrap inside).
2. **Five outer resilient_http boundaries** wrap to `GraphAPIError` AFTER retries are exhausted:
   - `_get_impl` — used by GET path
   - `_post_retrying` — used by retry-safe POST
   - `_post_no_retry` — used by `retry_safe=False` POST (D18)
   - `get_bytes` — public binary download method
   - `_paginate_one_page` — used by GET pagination
3. The wrap is centralized in the new static helper `GraphClient._wrap_transport_error(exc, *, where=...)`.
4. `GraphAPIError.status_code`'s `transport_only` set extended to include all error_codes from `_TRANSPORT_ERROR_CODE_MAP` so consumers see uniform `status_code=None` for transport-tier failures.

## What to verify

- The retry classifier in `src/assistant/core/resilience.py` will now see raw `httpx.TransportError` instances during retries (since the inner code re-raises raw). Confirm the classifier matches them and they retry as expected.
- All five outer boundaries correctly catch and wrap. No path leaks raw httpx exceptions to public callers.
- `_get_bytes_inner`'s tmpfile cleanup happens BEFORE the re-raise so no stale tempfiles leak.
- `_post_no_retry` still records breaker availability failures (the inner `isinstance(exc, httpx.TransportError)` check inside `_post_no_retry`'s breaker-acquired block).
- No unintended interaction between `_wrap_transport_error` and the existing `CircuitBreakerOpenError → GraphAPIError(error_code="breaker_open")` wrap.

## Convergence criteria

- **CONVERGED**: empty `findings` array OR only `disposition: "accept"` low-criticality observations.
- **NOT CONVERGED**: any `disposition: "fix"` finding at medium-or-above. ESCALATE to user.

## Output format — STRICT (same shape as rounds 1-3)

```json
{
  "review_type": "implementation",
  "target": "ms-graph-extension",
  "reviewer_vendor": "<your-vendor-name>",
  "findings": [...]
}
```

## Rules

- DO NOT modify any files.
- Output ONLY the JSON object.
- Be specific — file:line references.
- If converged, return `"findings": []` or only low-criticality `accept` items.
