# Implementation Review — observability (round 2)

You previously reviewed this branch in round 1 and identified 22 findings; 9 were fixed via consensus + manual cross-vendor clustering. This round verifies the round-1 fixes did not introduce regressions AND surfaces any *novel* issues you can find. Do NOT re-raise round-1 issues that have been addressed (listed below).

## Working directory

`/Users/jankneumann/Coding/agentic-assistant/.git-worktrees/observability`

## What changed since round 1

Run `git log --oneline 55196af..HEAD` to see the iter-2 commits. Round-1 fixes landed in commit `16c6e06`. Read `openspec/changes/observability/loop-state.json` IMPL_REVIEW.rounds[0] for the full fix-by-fix accounting.

**Fixed in round 1 (do NOT re-flag unless the fix is incorrect):**

| ID | What was fixed | Where to verify |
|---|---|---|
| A | `traced_harness` now emits `input_tokens`/`output_tokens` (was None) — extraction via `_last_usage` stash, defaults to (0, 0) | `src/assistant/telemetry/decorators.py` `_consume_usage`; `src/assistant/harnesses/sdk/deep_agents.py` `_extract_usage` |
| B | `docker-compose.langfuse.yml` now has `init-dummy-guard` service that fails the stack if DUMMY values would reach a non-localhost host; spec escalated D9 → req observability.14 | `docker-compose.langfuse.yml` lines 92-130 (init-dummy-guard); `langfuse-web.depends_on` long-form; `specs/observability/spec.md` Requirement "Dev Infrastructure Refuses DUMMY Credentials Outside Localhost" |
| C | Every Langfuse SDK ctx-mgr call wrapped in try/except via `_emit_observation`; `flush()` and `start_span` defensive too | `src/assistant/telemetry/providers/langfuse.py` `_emit_observation` (~line 90-130) |
| E | `wrap_extension_tool` / `wrap_http_tool` now also set `func=` when the source had it (sync invocation no longer breaks) | `src/assistant/telemetry/tool_wrap.py` `_traced_sync` + the `sync_callable` rebind at `from_function` |
| G | NoopProvider validators now unconditional (drop `if x is not None`); LangfuseProvider already was | `src/assistant/telemetry/providers/noop.py` lines 38-49; `_validate_*` in `base.py` typed `Any` |
| H | Empty-cred warning relocated to `factory._warn_once`; `TelemetryConfig.empty_creds_present` tuple plumbs the env var names; spec scenario amended | `src/assistant/telemetry/config.py` `empty_creds_present`; `src/assistant/telemetry/factory.py` `_init_provider` |
| I | Dead module-level `__getattr__` at langfuse.py:262 removed | langfuse.py end-of-file is now `def shutdown(...)` not `__getattr__` |
| J | Redundant `obs.update(metadata=md)` inside SDK ctx-mgr dropped | grep langfuse.py for `obs.update` — should be zero matches |
| K | `docs/observability.md` quickstart no longer claims Graphiti has separate tracing | docs/observability.md:34-39 |

**Deferred (do NOT re-raise unless materially different):**
- D: `messages` sanitization in `trace_llm_call` — req observability.7 scopes to attributes/metadata/error messages, NOT LLM input. Treated as spec-interpretation question.
- F: span `duration_ms` reflects SDK ctx-mgr exit time — Langfuse-UI concern; the decorator's measured value is what we record in metadata and is accurate.
- L: `wrap_extension_tool` BaseTool bypass log — single-vendor info, low priority.
- M: factory `atexit.register` bypasses `flush_hook.register_shutdown_hook` helper — production behavior is correct (singleton); test-side leak is minor.
- N: docs Stop-hook intro clarity — the existing intro at line 181 of docs/observability.md ("This repo does **not** install...") is sufficient.

## What to evaluate this round

1. **Verify round-1 fixes are correct** — for each fix ID above, read the cited code and confirm the fix actually addresses the original finding. If a fix is incomplete, regressed, or introduced a new issue, raise that as a finding.
2. **Test coverage of round-1 fixes** — every fix should have at least one regression test. Read `tests/telemetry/` for the new tests (search for "iter-2" or "Iter-2"). Flag any fix that lacks regression coverage.
3. **Surface novel issues** — anything you missed in round 1 because you were focused on the bigger blockers. Especially examine:
   - Test quality: are the iter-2 regression tests asserting the right invariants, or are they tautological / over-specified / under-specified?
   - Spec drift introduced by the iter-2 spec edits (req observability.14 added, observability.10 amended) — do the new scenarios match the implementation?
   - Cross-cutting effects: the `_consume_usage` helper reads `self._last_usage` and may interact with concurrent harness invocations sharing state — is this safe?
   - The `init-dummy-guard` shell script: are there shell-quoting / variable-expansion edge cases that would break the check?

## Out of scope

- The 11 pre-existing failures in `tests/http_tools/` — these predate the observability change.
- Style/format nits below medium criticality unless they bundle into a thematic finding.
- The round-1 deferred items (D, F, L, M, N) above unless you find new evidence.

## Output format

Output ONLY a single JSON document. Use the **synthesizer-compatible schema** (round 1 had schema friction we want to avoid):

```json
{
  "review_type": "implementation",
  "target": "observability",
  "vendor": "<your vendor id, e.g. codex|gemini>",
  "round": 2,
  "findings": [
    {
      "id": 1,
      "type": "correctness|security|spec_gap|contract_mismatch|performance|resilience|observability|style|architecture|compatibility",
      "criticality": "critical|high|medium|low",
      "description": "What is wrong, with reproducer or evidence. Reference specific lines: file_path:line_number.",
      "resolution": "Concrete fix, with file:line for changes. If multi-file, list them.",
      "disposition": "fix|defer|out-of-scope",
      "file_path": "src/path/to/file.py",
      "line_range": {"start": 123, "end": 123}
    }
  ]
}
```

**Criticality bar (matches round 1's translation):**
- `critical/high` (was "blocking"): spec violation, security issue, correctness bug, missing critical test
- `medium` (was "warning"): edge case missed, sub-optimal but not broken, drift between docs/code
- `low` (was "info"): polish, naming, optional improvement

**Type vocab** must be one of: correctness, security, spec_gap, contract_mismatch, performance, resilience, observability, style, architecture, compatibility.

**Caps**: 15 findings max. If clean, return an empty findings array — that's the convergence signal.

Be specific: a finding without a `file_path` (and `line_range` where applicable) is half useless. A finding without a `resolution` is half useless.
