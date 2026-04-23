# Round 2 Plan Review — Consensus Summary

**Date**: 2026-04-24
**Vendors**: claude (primary), codex (gpt-5.5), gemini
**Raw findings**: 19 (claude 6 + codex 7 + gemini 6)
**Round 1 → Round 2 trend**: 32 → 19 findings (↓ 41%)

## Convergence status: **ACHIEVED**

No critical findings. 3 confirmed high findings, all addressed in
iteration 3. Remaining items are low-criticality nits that fall under
ACCEPT per the iterate-on-plan skill's convergence criteria.

## Multi-vendor confirmed findings

| ID | Vendors | Criticality | Issue | Disposition |
|----|---------|-------------|-------|-------------|
| R2-C1 | claude + codex + gemini | high | MB vs MiB unit mismatch between design.md and spec.md | FIXED (iteration 2.5 — preemptive, before codex/gemini dispatched round-2 findings) |
| R2-C2 | claude + codex + gemini | medium | Task 4.5 cited non-existent spec scenario | FIXED (iteration 2.5 — added 3 scenarios: Required, Optional, Typeless) |
| R2-C3 | codex + gemini | high | `openapi-spec-validator` dependency used in task 1.5 but not added until Phase 9 | FIXED (iteration 3 — moved to Phase 0 alongside pytest-httpserver) |
| R2-C4 | claude + codex + gemini | medium | Task 6.4 `test_timeout_skipped` without named spec scenario | FIXED (iteration 2.5 — added "Discovery timeout skipped with warning" scenario) |

## Single-vendor confirmed findings addressed

| ID | Vendor | Criticality | Issue | Disposition |
|----|--------|-------------|-------|-------------|
| R2-C5 | codex | high | 10 MiB cap enforced via `response.content` (buffers entire body before check) | FIXED (iteration 3 — switched D9 + spec to streaming `aiter_bytes` with running byte counter) |
| R2-C6 | codex | medium | `httpx.Timeout(10.0, connect=5.0)` is not a wall-clock total, misleading | FIXED (iteration 3 — D9 now documents per-operation limits explicitly, notes no wall-clock total, suggests `asyncio.wait_for` as future add-on) |
| R2-C7 | codex | medium | proposal.md claims `__init__.py` public API includes `discover_tools`, contradicting D8 | FIXED (iteration 3 — proposal.md now describes the leaf-only re-exports with cross-reference to D8) |
| R2-C8 | codex | medium | design.md test layout still declared `test_cli_list_tools.py` | FIXED (iteration 3 — moved to `tests/test_cli.py` in layout diagram + Testing Strategy paragraph) |
| R2-C9 | claude | low | Stale test reference in D9 Consequence ("tests 6.1 and 4.1") | FIXED (iteration 3 — now cites 6.4/6.5/6.6/4.6) |
| R2-C10 | gemini | low | `urllib.parse.quote` default `safe="/"` leaves `/` un-encoded — breaks the path-encoding test | FIXED (iteration 3 — spec + task 4.2 now specify `safe=""` explicitly) |

## Accepted (low-criticality nits, not blocking)

| ID | Vendor | Criticality | Reason |
|----|--------|-------------|--------|
| — | gemini | medium | `$ref` ValueError ambiguity (cyclic vs external both raise ValueError) — can use different exception subclasses in implementation if useful; not a plan-level blocker |
| — | claude | low | work-packages.yaml priority gap (0, 1, 2, 2, 3, 5) — cosmetic; DAG scheduler doesn't require gapless numbering |
| — | claude | low | Task 0.4 fixture persona updates don't name specific files — "update `tests/fixtures/personas/`" is clear enough; specific YAML changes belong in implementation |

## Round-1 round-2 regression analysis

Round-2 vendors were explicitly instructed to scan for regressions from
iteration 2 edits. Regressions found and fixed:

1. **MB/MiB unit drift** (R2-C1) — classic copy-paste regression when
   adding new security text. Caught by all three vendors.
2. **Task → scenario cross-reference drift** (R2-C2, R2-C4) — added
   tasks cited scenario names before writing the scenarios. Caught by
   all three vendors.
3. **Stale test references in design.md** (R2-C8, R2-C9) — the C10
   fix in iteration 2 updated tasks/work-packages but not the
   design.md narrative. Caught by codex + claude.

These are exactly the kind of multi-edit-across-files drift that a
single-vendor review would miss. Multi-vendor convergence catches them
because different vendors read different files and cross-reference
differently.

## Ready for IMPLEMENT

- All critical and high findings resolved.
- All medium findings that would cause implementation rework resolved.
- Remaining low findings documented as ACCEPTED with rationale.
- `openspec validate http-tools-layer --strict`: green.
- 3-way convergence: claude (0 crit, 1 hi, 2 med, 3 lo) + codex
  (0 crit, 2 hi, 5 med, 0 lo) + gemini (0 crit, 1 hi, 3 med, 2 lo),
  all high findings addressed.

**Transition: PLAN_REVIEW → IMPLEMENT** per autopilot state machine.
