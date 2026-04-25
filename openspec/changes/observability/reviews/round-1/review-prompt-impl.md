# Implementation Review — observability (round 1)

You are reviewing the implementation on the `openspec/observability` branch of the **agentic-assistant** repo against its OpenSpec proposal. Produce a structured critique.

## Working directory

`/Users/jankneumann/Coding/agentic-assistant/.git-worktrees/observability`

## How to read the change

Run `git diff main..HEAD` to see all 65 changed files (~8.5K insertions). Then deep-read against requirements:

- `openspec/changes/observability/proposal.md` — Why, What Changes, Impact, Selected Approach (Approach A: typed Protocol + 3-level degradation + 6 hook sites + sanitization + ContextVar propagation)
- `openspec/changes/observability/design.md` — 13 design decisions
- `openspec/changes/observability/specs/observability/spec.md` — 13 ADDED Requirements (D5 sanitization scenario "List elements under safe keys are still sanitized" was added by /iterate-on-implementation iter 1)
- `openspec/changes/observability/specs/{harness-adapter,delegation-spawner,extension-registry,capability-resolver,http-tools}/spec.md` — 1 ADDED Requirement each
- `openspec/changes/observability/tasks.md` — 43 tasks (42/43 done; task 5.5 deferred as optional smoke test)
- `openspec/changes/observability/work-packages.yaml` — 4 work packages (wp-contracts, wp-hooks, wp-devops, wp-integration)
- `openspec/changes/observability/change-context.md` — Requirement Traceability Matrix (18 reqs traced to source + tests)
- `openspec/changes/observability/impl-findings.md` — iter 1 findings already triaged + 4 deferred-to-this-review items + 1 out-of-scope follow-up

## Pre-flagged context

The IMPLEMENT phase recorded 7 deviations (see `loop-state.json#deviations_for_impl_review`). Six are valid implementation choices with stated rationale; the seventh was **corrected** during iter 1 (trace_delegation.task IS sanitized at langfuse.py:155 — original deviation note overstated the privacy risk). Do NOT relitigate the six valid deviations unless you find new evidence; do verify the deviation-7 correction is accurate by inspecting `src/assistant/telemetry/providers/langfuse.py:155`.

Iter 1 fixed one defect (sanitize.py list-recursion under SAFE_FIELDS keys) and committed at `55196af`. The fix is in scope for your review — confirm correctness or flag concerns.

The four findings deferred to this review (in `impl-findings.md`):
- **F-3**: Empty-credential warning fires at `config.from_env` rather than via factory `_warn_once` dedup mechanism (architectural coherence vs spec letter)
- **F-4**: Module-level `__getattr__` at `langfuse.py:262` is dead code (raises AttributeError, which is the default behavior anyway)
- **F-5**: `noop.trace_tool_call` quietly returns on missing `tool_kind`; `langfuse.trace_tool_call` raises (validator asymmetry)
- **F-6**: `docs/observability.md` Stop-hook section lacks a 1-2 sentence intro

These are below the iter-1 medium fix threshold — please confirm or escalate them, plus surface anything novel you find.

## What to evaluate

Focus on these eight axes; flag any concrete issue as a structured finding (do NOT enumerate praise, only issues):

1. **Spec compliance** — does the implementation match each Requirement and scenario? Trace specific Req IDs (e.g. observability.1, harness-adapter.1) to source files and tests. Use the RTM in `change-context.md` as your map. Flag any requirement that has a missing test, a test that does not actually verify the requirement, or an implementation that contradicts the spec text.
2. **Correctness** — logic bugs, off-by-one, wrong type narrowing, race conditions, missed exception paths, wrong invariant. Especially scrutinize: the 3-level degradation state machine in `factory.py`; the `traced_harness` / `traced_delegation` decorators in `decorators.py` (exception path emits trace before re-raise); the `wrap_extension_tools` and `wrap_http_tool` in `tool_wrap.py` (they accept `Any` with passthrough for non-StructuredTool — confirm this does not silently drop traces).
3. **Security** — sanitization regex chain ordering (most-specific-first); known-safe field policy for SAFE_FIELDS; persona-passthrough rationale; outbound-only posture in `__init__.py` (no fastapi/flask/aiohttp.web/grpc imports anywhere under `src/assistant/telemetry/`); `DUMMY-` prefix on all eight `LANGFUSE_INIT_*` values in `docker-compose.langfuse.yml` plus the localhost-guard sidecar logic.
4. **Concurrency** — singleton lifecycle in `factory.py` (double-checked locking with module-level lock); ContextVar isolation across `asyncio.gather` (concurrent delegations must each see their own sub-role per PEP 567); `atexit.register` placement and idempotency.
5. **Performance** — NoopProvider zero-allocation posture (every method body should be effectively `return None` apart from the conditional enum validation); sanitization cost on every span attribute (regex chain runs on every string in metadata).
6. **Testability and test quality** — coverage gaps relative to spec scenarios, brittle mock patterns, timing-sensitive assertions, ordering assumptions. Look for tests asserting things the impl does not actually do, or tests that pass for the wrong reason.
7. **Documentation drift** — does `docs/observability.md` match the implementation? Does the `flush_hook.py` docstring contain "Delivery guarantees" content per req observability.13? Does `__init__.py` say "outbound-only"?
8. **Spec-vs-impl drift** — places where the implementation does extra things not specified, OR where the spec promises something the impl does not deliver. Especially: every `trace_*` call site should appear in the RTM Files Changed column.

## Out of scope

- The 11 pre-existing failures in `tests/http_tools/test_discovery.py` and `tests/http_tools/test_openapi.py` (FileNotFoundError on archived fixtures). These predate the observability change — do NOT raise findings about them.
- Style/format nits below the medium threshold unless they bundle into a thematic finding.
- The valid deviations 1-6 in `loop-state.json#deviations_for_impl_review` (Langfuse v3 API drift, auth_check absence, passthrough for MagicMock tools, PEP 695 generics, dual `set_assistant_ctx`, no `LANGFUSE_INIT_*` on the worker service) — do NOT relitigate unless new evidence.

## Output format

Output ONLY a single JSON document conforming to the schema at `agentic-coding-tools/openspec/schemas/review-findings.schema.json`. No prose, no markdown wrapper, no commentary before or after.

Required shape:

```json
{
  "review_type": "implementation",
  "target": "observability",
  "vendor": "<your vendor id, e.g. codex|gemini>",
  "round": 1,
  "findings": [
    {
      "id": "impl-<short-slug>-1",
      "severity": "blocking|warning|info",
      "type": "correctness|security|spec_gap|contract_mismatch|performance|resilience|observability|style|architecture|compatibility",
      "title": "Short title",
      "description": "What is wrong, with reproducer or evidence. Reference specific lines: file_path:line_number.",
      "location": {
        "file": "src/path/to/file.py",
        "line": 123
      },
      "spec_ref": "observability.7 (D5)",
      "proposed_fix": "Concrete fix, with file:line for changes. If multi-file, list them."
    }
  ]
}
```

**Severity bar**:
- `blocking`: spec violation, security issue, correctness bug, missing critical test
- `warning`: edge case missed, sub-optimal but not broken, drift between docs/code
- `info`: polish, naming, optional improvement

**Type vocab** must be one of: correctness, security, spec_gap, contract_mismatch, performance, resilience, observability, style, architecture, compatibility.

Cap at 25 findings. If you find more, group thematically (one finding listing locations).

Be specific: a finding without a `location.file` (and `line` where applicable) is half useless. A finding without a `proposed_fix` is half useless.
