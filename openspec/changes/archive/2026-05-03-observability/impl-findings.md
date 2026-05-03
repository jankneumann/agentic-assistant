# Implementation Findings — observability

This document accumulates findings discovered during `/iterate-on-implementation` runs and any subsequent multi-vendor review (autopilot's IMPL_REVIEW phase). Each iteration appends a section.

Threshold for in-band fix: **medium** (criticality: critical > high > medium > low).
Findings below threshold are listed but deferred. Out-of-scope findings are flagged for a separate proposal.

## Seeded deviations from IMPLEMENT phase

These were recorded in `loop-state.json#deviations_for_impl_review` at IMPLEMENT close — pre-flagged so review effort focuses on novel issues rather than re-discovering known gaps.

1. **Langfuse v3 SDK API drift** — `start_as_current_observation(as_type=...)` replaces `trace()`/`generation()`. Design predates v3; implementation matches v3.
2. **`auth_check()` unavailable in v3** — auth-failure detection moved to factory level-3 degradation (catch on construction or first emission).
3. **`wrap_extension_tool` / `wrap_http_tool` accept `Any` with passthrough** for non-StructuredTool inputs (kept tests with MagicMock tools green; spec language targets StructuredTool).
4. **PEP 695 generic syntax** (`def traced_harness[R]`) instead of `TypeVar` — Python 3.12 idiom, satisfies ruff UP047.
5. **`set_assistant_ctx` invoked in BOTH `run` and `export` CLI commands** so export path is also tagged.
6. **Langfuse-worker compose service intentionally lacks `LANGFUSE_INIT_*`** (only web service performs headless init in v3 self-hosting).
7. **`trace_delegation.task` emitted verbatim ≤256 chars (req observability.4)** — ~~short delegation prompts containing sensitive content would land in Langfuse without sanitization~~. **Updated 2026-04-25 (Iter 1)**: re-reading `src/assistant/telemetry/providers/langfuse.py:155` shows `input={"task": sanitize(task)}` — the task IS run through the 15-pattern sanitization chain at emission. The decorator passes the verbatim short task (or sha256 hash if >256) to the provider, but the provider applies `sanitize()` before sending to Langfuse. Privacy-posture concern is materially reduced: secret-format substrings in short tasks are scrubbed. The remaining residual risk is non-secret-format PII (e.g., free-form prose containing names) which the regex chain does not catch — that is a spec-level concern about what counts as "sensitive content" and belongs in a separate proposal if treated as out-of-scope here.

## Iteration 1 — 2026-04-25

### Findings table

| # | File:Line | Type | Crit | Description | Disposition |
|---|---|---|---|---|---|
| 1 | `src/assistant/telemetry/sanitize.py:141-142` | security/edge-case | medium | `_sanitize_value` recursively descends into lists carrying the parent key forward. If a list lives under a `SAFE_FIELDS` key (e.g. `{"persona": ["a", "sk-lf-x"]}`), every string element is exempted from sanitization because the per-element call sees `key in SAFE_FIELDS`. SAFE_FIELDS values are spec'd as scalar strings, so this is defense-in-depth rather than current exploit, but the asymmetry with dict-recursion (which re-keys per child) is surprising and would silently leak secrets if any future call site ever passed a list under one of the safe keys. | **FIX in iter 1** |
| 2 | `loop-state.json#deviations_for_impl_review[6]` | doc/state | low | Deviation note overstates privacy risk — actual code at `langfuse.py:155` calls `sanitize(task)`. | **FIX in iter 1** (corrected above + state update) |
| 3 | `src/assistant/telemetry/config.py:97-103` vs `factory._warn_once` | architecture | low | Empty-credential warning emitted at `from_env()` level rather than via the factory's `_warn_once` dedup mechanism. Spec-compliant (observability.10 pins emission to `from_env()`) but inconsistent with the rest of the warning architecture; in practice the singleton ensures single emission. | **DEFER to IMPL_REVIEW** — multi-vendor arbitration on architectural coherence vs spec letter |
| 4 | `src/assistant/telemetry/providers/langfuse.py:262-264` | dead-code | low | Module-level `__getattr__` raises `AttributeError(name)`, which is the default behavior when a missing attr is looked up on a module. The function adds no behavior. | **DEFER to IMPL_REVIEW** — cleanup candidate |
| 5 | `src/assistant/telemetry/providers/noop.py:40-42, 46-48` | edge-case | low | Validators only fire when `tool_kind`/`op` is provided. `noop.trace_tool_call(**{})` quietly returns; `langfuse.trace_tool_call(**{})` raises (since validator runs unconditionally). Protocol type hints make this nearly impossible to reach in practice (keyword args are required), but the noop/langfuse asymmetry is worth a note. | **DEFER to IMPL_REVIEW** |
| 6 | `docs/observability.md` Stop-hook section | UX/docs | low | External tool is referenced without a 1-2 sentence intro explaining what the hook does. | **DEFER to IMPL_REVIEW** |

### Findings dismissed during triage (agent misread code)

- **F-dismissed-1**: claimed `_warned_levels` dedup contract is undocumented — actually documented in `factory.py:20-24` module docstring.
- **F-dismissed-2**: claimed `atexit.register()` is outside the lock — actually inside the `with _provider_lock:` block at `factory.py:129`.
- **F-dismissed-3**: claimed `trace_memory_op` decorator drops target on kwargs-only callers — actually has explicit `else kwargs.get(...)` fallback at `decorators.py:244-251`.

### Iteration 1 fixes applied

- **F-1**: list-recursion in `_sanitize_value` now ignores parent-key safety — string elements in lists are always run through the redaction chain. New scenario "List elements under safe keys are still sanitized" added to `specs/observability/spec.md` Secret Sanitization Requirement; corresponding test added to `tests/telemetry/test_sanitize.py`.
- **F-2**: deviation #7 note corrected in `loop-state.json` (and above) to reflect that `langfuse.py:155` calls `sanitize(task)`.

### Findings deferred to IMPL_REVIEW (multi-vendor convergence)

F-3, F-4, F-5, F-6 are visible to vendors via this document so they can confirm or escalate during the next phase.

### Out-of-scope follow-up: `tests/http_tools/` fixture-path bitrot

11 pytest failures in `tests/http_tools/test_discovery.py` and `tests/http_tools/test_openapi.py` — every failure is `FileNotFoundError` for fixtures at `openspec/changes/http-tools-layer/contracts/fixtures/sample_openapi_v3_*.json`. The change `http-tools-layer` was archived to `openspec/changes/archive/2026-04-24-http-tools-layer/contracts/fixtures/...` on 2026-04-24 (commit `ed6008c`); the tests still reference the unarchived path.

- **Scope**: NOT introduced by the observability change. Verified by `git stash` + checkout of `a079754` (IMPLEMENT-phase HEAD) — the same 11 failures reproduce.
- **Disposition**: file as a follow-up issue. Right fix is to move the fixtures into a stable `tests/http_tools/fixtures/` location so test code never reaches into `openspec/changes/`. Quick fix (path bump to the archive location) would couple tests to an archive directory whose name embeds the archive date — fragile and worse than a real refactor.
- **Action item**: file `gh issue` with label `followup` + `openspec:http-tools-layer` after merge, summarising the FileNotFoundError pattern and pointing at the archived fixture location.

