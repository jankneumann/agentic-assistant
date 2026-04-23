# Session Log: http-tools-layer

---

## Phase: Plan (2026-04-23)

**Agent**: claude-code (Opus 4.7, 1M context) | **Session**: autopilot-run-1

### Decisions

1. Approach A — dedicated `http_tools/` module with the registry injected into `CapabilityResolver`. Minimal surface; defers any `ToolSource` abstraction to P17 when a second concrete source exists. Matches the three roadmap acceptance outcomes literally.
2. Discovery wire format — OpenAPI 3.x. Industry standard; richer schemas than a bespoke manifest; services can document with existing tooling. Fallback from the `/openapi.json` endpoint to `/help` for convenience.
3. Integration shape — extend the existing `DefaultToolPolicy` rather than introduce a new policy or source abstraction. The registry goes on the constructor; `authorized_tools` merges and filters.
4. Mock server — pytest-httpserver. Real HTTP on a random port exercises the full httpx stack. Added as a dev dependency.
5. Auth scope — static bearer and api-key only. OAuth / refresh deferred to P5 (ms-graph-extension) and P10 (extension-lifecycle). `resolve_auth_header` is a pure function.
6. Runtime Pydantic model generation via `pydantic.create_model()` — D1 in design. Personas can declare arbitrary `tool_sources`, so pre-generated typed stubs would break clone-and-run. Runtime cost is a one-time startup hit measured in milliseconds per operation.
7. Single shared `httpx.AsyncClient` per process — D2 in design. Connection pooling across sources is more efficient than per-tool clients; lifecycle managed via `weakref.finalize`.
8. Registry keys formatted as source colon operation — D3 in design. Namespaces across services; keeps `role.preferred_tools` expressive; aligns with the already-forward-declared `content_analyzer:search` preferences in the archived `add-teacher-role` change.
9. Discovery failures skip the source; per-invocation failures raise — D4 in design. A half-working assistant beats a non-starting one; invocation errors must bubble so the LLM does not fall back to a misleading empty answer.
10. Five work packages across the coordinated tier — `wp-http-tools-leaves` at priority 1; `wp-http-tools-composite` and `wp-policy` in parallel at priority 2; `wp-cli` at priority 3; `wp-integration` at priority 4. Non-overlapping `write_allow` scopes.

### Alternatives Considered

- Approach B (a `ToolSource` Protocol with `HttpToolSource` as first implementation): rejected as premature abstraction. Only one concrete source in sight for P3; generalization should wait until P17 introduces MCP as a second source.
- Approach C (discovery owned by `DefaultToolPolicy`, lazy and cached): rejected because it contradicts the explicit roadmap acceptance outcome that the CLI calls discovery at startup. Fusing discovery into the policy also harms testability.
- Custom JSON manifest instead of OpenAPI: rejected. OpenAPI parameters and requestBody schemas map more cleanly to Pydantic; services can be auto-introspected with existing tooling.
- Pre-generated Pydantic models via `datamodel-code-generator`: rejected. Requires a build step per persona; breaks clone-and-run for personas that configure new `tool_sources`.
- respx as the mock layer: rejected in favor of pytest-httpserver because real-socket tests catch more regressions.
- Full credential provider abstraction: rejected as over-building for P3 scope; bearer and api-key suffice.

### Trade-offs

- Accepted runtime reflection cost at CLI startup over static codegen because personas are user-configured and the cost amortizes across the entire session.
- Accepted a MODIFIED tool-policy spec coupling over introducing a new policy type because the existing `DefaultToolPolicy` is already the right seam; a second policy would fragment the filtering path.
- Accepted a slightly chunky `wp-http-tools-leaves` package (three leaf modules plus tests, roughly 320 LOC) over finer-grained splitting to keep the total count at four implementation packages plus one integration package, within the complexity-gate default.
- Accepted silent skip-on-failure for per-source discovery errors over fail-fast to keep the assistant usable during partial service outages; this trades some discoverability — users must read logs — for availability.

### Open Questions

- [ ] Does any persona already configure `tool_sources` with a live base_url that we should smoke-test against? Task 11.4 is manual; the pytest suite covers the mock path.
- [ ] When P9 `error-resilience` lands, will the retry decorator wrap `discover_tools` or the tool coroutines? Design decision for P9; not blocking here.
- [ ] Is `docs/architecture-analysis/*.json` worth generating now, or defer until a phase that actually needs the component graph? The `refresh-architecture` skill exists but lacks a `make architecture` driver in this repo.

### Context

Plan authored via `/autopilot http-tools-layer` — the PLAN phase of the autopilot state machine. The coordinator is available at `coord.rotkohl.ai` over HTTP transport; tier selection yielded coordinated because all capabilities are present and three vendor CLIs are available for downstream review convergence. The dependency `capability-protocols` was archived 2026-04-20 and provides the `ToolPolicy` protocol that this change's registry plugs into.

---

## Phase: Plan Iteration 1 (2026-04-23)

**Agent**: claude-code (Opus 4.7, 1M context) | **Session**: autopilot-run-1

### Decisions

1. **D8 added to design — minimal `http_tools/__init__.py`.** `__init__.py` re-exports only the leaf symbols (`AuthHeaderConfig`, `resolve_auth_header`, `HttpToolRegistry`). Consumers import composite symbols via their specific module path. Fixes a real problem the DAG had: under coordinated tier, `wp-http-tools-leaves` merges before `wp-http-tools-composite`, and an eager `from .discovery import discover_tools` in `__init__.py` would break package imports at every intermediate state.
2. Work-packages `deny` scope entry added to `wp-http-tools-composite` explicitly forbidding writes to `__init__.py`. The lock rationale now cites D8 so reviewers do not re-open the question.
3. New spec scenario — Swagger 2.0 skip-with-warning. Design already said this was the intended behavior; it was unspecified. Added under the HTTP Tool Discovery requirement and matching tasks 1.4 (fixture) and 6.3 (test).
4. The `caplog` assertion pattern is now explicitly required in task 6.1 and 6.3. Implementors have a concrete pytest mechanism to verify the warning-log scenarios.
5. Proposal Why section reworded to state OpenAPI at `{base_url}/openapi.json` is the primary discovery endpoint, with `{base_url}/help` as a 404 fallback. Removes the ambiguity introduced by the roadmap shorthand that referred to help-based discovery as primary.

### Alternatives Considered

- **Move `__init__.py` ownership to `wp-integration` (final package)**: rejected because leaves would have no importable package surface, breaking its own tests.
- **Delete `__init__.py` re-exports entirely; require fully-qualified imports everywhere**: rejected because `HttpToolRegistry` is widely consumed and benefits from the shorter path. Compromise is the minimal re-export in D8.
- **Pre-seed `__init__.py` with `from .discovery import discover_tools  # noqa: lazy`**: rejected — lazy-import gymnastics are fragile and the naïve reader assumes the symbol is always importable.

### Trade-offs

- Accepted a small import-style asymmetry (leaf symbols via package root, composite symbols via module) for a strict DAG-import invariant: `python -c "import assistant.http_tools"` never fails between merge points.
- Accepted an extra fixture + test task (roughly 50 LOC) to keep the Swagger 2.0 behavior specified rather than silently correct.

### Open Questions

- [ ] Should `__init__.py` eventually re-export `discover_tools` once the composite package lands? Proposed: yes, as an additive follow-up after P3 archives. Tracked in D8 consequence section.

### Context

Iteration 1 addressed 1 high-parallelizability finding (H1), 1 high-completeness finding (H2), and 2 medium findings (M1 clarity, M2 testability). One low finding (L1 — per-invocation debug logging) deferred to P4 `observability`. Validation green. Ready for vendor review dispatch.

---

## Phase: Plan Iteration 2 (2026-04-24) — Round 1 Convergence Review

**Agent**: claude-code (Opus 4.7, 1M context) + codex-local (gpt-5.5) + gemini-local | **Session**: autopilot-run-1

### Decisions

1. **D9 added — HTTP client security posture.** Explicit `timeout=Timeout(10.0, connect=5.0)`, `follow_redirects=False`, `verify=True`, 10 MiB response-size cap, credential redaction in all warning logs. Raised by claude + gemini independently as a critical security surface gap. The assistant makes outbound HTTP calls with credentials; permissive defaults are a direct attack surface.
2. **D10 added — OpenAPI `$ref` resolution.** Intra-document pointers are resolved; external refs skip the operation with a warning; cyclic refs raise. All three vendors (claude, codex, gemini) flagged this independently after noticing `sample_openapi_v3_1.json` itself uses `$ref: "#/components/schemas/ItemCreate"`. Two new contract fixtures (cyclic + external) added under tasks 1.6 and 1.7.
3. **D11 added — persona `auth_header` schema evolution.** The existing `persona.py:109` flattens `auth_header_env` to a bare string via `_env(...)`; the spec's `resolve_auth_header` expects a `{type, env, header?}` dict. Rather than forcing one shape, P3 supports both — the legacy flat form auto-normalizes to `{type: "bearer", env: VAR_NAME}`. Flagged as critical by claude and high by codex.
4. **D2 rewritten.** Removed the `weakref.finalize` + `asyncio.get_event_loop().run_until_complete(client.aclose())` pattern from the risks table. `aclose()` is async and weakref callbacks run synchronously outside the event loop; the pattern cannot work. Replaced with `async with httpx.AsyncClient(...)` scoped to `_run_repl` and `_list_tools`.
5. **New Phase 0 added — persona schema + pytest-httpserver dev dep.** Moving the dep install from Phase 9 (last) to Phase 0 (first) reflects the real dependency ordering: Phase 6 and Phase 8 tests import `pytest_httpserver`. Phase 0 also covers the `persona.py` extension from D11 and updates to `tests/fixtures/personas/`.
6. **New work-package `wp-prep` at priority 0.** Owns Phase 0 tasks (persona schema + dev dep + fixture personas). All other packages now depend on it. Locked on `core:persona:tool_sources` and `deps:pyproject` keys.
7. **`wp-cli` scope narrowed.** Removed `tests/http_tools/test_cli_list_tools.py` from `write_allow` — the file name appeared in proposal.md §6 but no task actually created it; 8.1/8.2 place the tests in `tests/test_cli.py`. Claude flagged the scope ambiguity.
8. **`defaults.auto_loop` thresholds raised.** `max_loc` 1500 → 1800; `max_packages` 4 → 5. The added security posture, `$ref` resolution, content-type handling, and persona schema tasks expand the implementation from ~1000 LOC to ~1200 LOC. Complexity-gate pre-check confirmed the raised thresholds still pass with `val_review_enabled=true` (unchanged) and `security-review` checkpoint (unchanged).
9. **10 of 14 substantive findings addressed in this iteration; 4 accepted as non-blocking.** Full accounting in `reviews/round-1/synthesis.md`. Accepted items are all either (a) low-criticality nits, (b) deferred performance targets already documented in D9, (c) CLI subcommand scenarios inherited from the P1 spec that are out of P3 scope, or (d) false positives like the `max_packages=4` warning (integration packages are excluded by complexity_gate).
10. **Spec additions are all `ADDED` clauses or new scenarios under existing Requirements; no MODIFIED existing behavior.** This keeps the diff reviewable and preserves the existing contract. `openspec validate --strict` green after all edits.

### Alternatives Considered

- **Only support structured `auth_header` dict (no legacy flat form compat)**: rejected. Every existing persona fixture uses `auth_header_env`; breaking them all just to simplify the auth resolver is a poor trade. D11 compromise adds ~5 lines of normalization logic.
- **Keep the `weakref.finalize` pattern with a different callback shape**: rejected. The fundamental problem is that weakref callbacks run synchronously and `aclose()` is a coroutine. No callback shape fixes that; structural `async with` is the only clean answer.
- **Add a dedicated persona-level `allowed_tools` authorization layer in P3**: rejected. Codex flagged a proposal/design mismatch; the resolution is to clarify (proposal Why paragraph) that per-source authorization is deferred, with per-role `preferred_tools` filtering covering the P3 need. No new component needed.
- **Fold the new security scenarios into existing Requirements rather than adding a new Requirement**: rejected. "HTTP Client Security Posture" is load-bearing enough to warrant its own Requirement; bundling it under an existing one would bury the 10 MiB cap and redirect refusal in unrelated prose.

### Trade-offs

- Accepted a larger plan surface (three new design decisions, six new scenarios, four new tasks) in exchange for eliminating three categories of implementation ambiguity (security posture, `$ref` semantics, auth schema). The alternative — defer to implementation-time discovery — would bleed rework into the IMPLEMENT phase where it's harder to review in aggregate.
- Accepted one extra work-package (`wp-prep`) and the serialization cost it introduces (everything depends on it) because the persona schema change is genuinely blocking for downstream tests. The serialization is unavoidable; the only alternative is duplicating the schema evolution across three later packages.
- Accepted raising `max_packages` from 4 to 5 rather than collapsing packages. Collapsing `wp-http-tools-composite` and `wp-policy` would merge two non-overlapping `write_allow` scopes into one, removing parallelism; collapsing `wp-prep` into `wp-http-tools-leaves` would put persona.py edits into a package whose lock is already on `http_tools/__init__.py`.

### Open Questions

- [ ] Will any real persona fixture hit the 10 MiB response cap during `--list-tools` smoke-testing in task 11.4? Unlikely for typical OpenAPI docs; noted as a manual-test observation item.
- [ ] When P9 `error-resilience` lands, does retry policy apply to discovery calls (which skip on failure anyway) or only to per-tool invocations? Design decision for P9; not blocking here.
- [ ] Should `AuthHeaderConfig` eventually grow to support OAuth refresh flows in P5, or will that be a separate `OAuthConfig` type? Leaving that to P5's design phase.

### Context

Iteration 2 addressed the Round 1 multi-vendor plan review. Three vendors dispatched in parallel (claude, codex gpt-5.5, gemini) produced 32 raw findings. The ConsensusSynthesizer's string-similarity clustering did not match findings across vendors (different prose, same underlying issue), so clustering was done manually against the source findings JSONs. Ten substantive issues addressed; four accepted as non-blocking with rationale documented in `reviews/round-1/synthesis.md`. Validation green. Ready for Round 2 review dispatch.

---

## Phase: Plan Iteration 3 (2026-04-24) — Round 2 Convergence Review

**Agent**: claude-code (Opus 4.7, 1M context) + codex-local (gpt-5.5) + gemini-local | **Session**: autopilot-run-1

### Decisions

1. **Convergence achieved in round 2.** 32 round-1 findings → 19 round-2 findings (↓ 41%). No critical findings in round 2. All high findings resolved in iteration 3; remaining items are low-criticality nits accepted with documented rationale. Transition PLAN_REVIEW → IMPLEMENT.
2. **Streaming size-cap enforcement (R2-C5).** Codex flagged that the round-1 D9 wording used `response.content` which buffers the entire body before any size check runs — defeating the defense. D9 and the spec now specify streaming via `response.aiter_bytes(chunk_size=65_536)` with a running byte counter that aborts and raises `ValueError` at the 10 MiB threshold. `response.content` is explicitly forbidden on unverified responses. This is the single most important substantive correction in iteration 3.
3. **httpx.Timeout wall-clock clarification (R2-C6).** The phrase "total 10s, connect 5s" in round-1 D9 was misleading; HTTPX's Timeout constructor sets per-operation limits (read, write, pool, connect) independently. Updated wording to document what the call actually does and to flag that a wall-clock total budget would require wrapping discovery in `asyncio.wait_for(...)` — left as a future add-on.
4. **Dependencies moved fully to Phase 0 (R2-C3).** Both codex and gemini flagged that `openapi-spec-validator` was used in task 1.5 but not installed until Phase 9 — same bug pattern as the pytest-httpserver fix we already applied in iteration 2. Merged both deps into task 0.1 so the entire Phase 0 `wp-prep` package owns the dev-dep installation.
5. **`urllib.parse.quote(safe="")` explicit (R2-C10).** Gemini caught that the default `safe="/"` leaves `/` un-encoded. The path-encoding scenario (`"foo/bar"` → `"foo%2Fbar"`) would fail with the default. Spec + task 4.2 now name the argument explicitly.
6. **Stale narrative references cleaned up (R2-C7, R2-C8, R2-C9).** Iteration-2 edits updated the load-bearing clauses (scope, tasks, spec) but left stale references in the design.md test-layout diagram, Testing Strategy paragraph, D9 Consequence sentence, and proposal.md's bullet about `__init__.py` public API. All reconciled with D8.
7. **MB/MiB unit mismatch (R2-C1) fixed preemptively.** All three vendors independently found this in round 2. I applied the fix between round-2 dispatch and when codex/gemini returned findings, so the vendors were reviewing an already-fixed-in-my-local-edit state. 3-way confirmation validates the autopilot review pattern.
8. **Task 4.5 scenario names (R2-C2) fixed preemptively.** Added three new scenarios to the spec — Required JSON Schema field, Optional field uses declared default, Typeless field is Any — plus renamed task 4.5's scenario references. 3-way vendor agreement.
9. **New task 4.6 — invocation-side security propagation tests.** The round-1 "HTTP Client Security Posture" Requirement body said per-tool invocation propagates the error, but no scenarios tested that path. Added three invocation-side scenarios (oversized response raises, redirect raises, timeout raises) plus task 4.6 that tests them via stubbed httpx responses. Fills a real testability gap that slipped past round 1.
10. **Acceptance list documented in `reviews/round-2/synthesis.md`**: (a) `ValueError` ambiguity between cyclic and external `$ref` cases — can use exception subclasses at implementation time if useful, not a plan blocker; (b) work-packages.yaml priority numbering gap — cosmetic, DAG scheduler doesn't require gapless numbering; (c) task 0.4 fixture-persona update lacks specific file names — the task directory pointer is clear enough, specific YAML edits are implementation-level detail.

### Alternatives Considered

- **Run a third review round to absorb the iteration-3 edits**: rejected. Convergence signal is strong (32 → 19 findings, no round-2 criticals, all highs fixed, no new architectural issues surfaced). Additional rounds would likely surface ever-diminishing low-criticality nits; marginal value less than the ~5 minutes of review time. The autopilot skill's convergence criteria (no critical, all high addressed) are met.
- **Add an `asyncio.wait_for` wall-clock wrapper in P3** (R2-C6): deferred. Per-operation timeouts + 10 MiB cap give a bounded-in-practice guarantee; the incremental safety of a hard wall-clock budget is not worth the added complexity for P3. P9 `error-resilience` can add it.
- **Use exception subclasses for `$ref` errors** (gemini accepted-medium): deferred to implementation phase. A single `ValueError` with a descriptive message is sufficient for the spec; if IMPL_ITERATE surfaces a need to distinguish programmatically, a small refactor is cheap.
- **Commit the two preemptive-fix items (R2-C1, R2-C2) as a separate iteration-2.5 commit**: rejected. The work is logically one iteration-3 bundle; splitting the commit would fragment the autopilot evidence trail.

### Trade-offs

- Accepted ~120 additional LOC of plan-document edits (streaming detail in D9, precise timeout wording, three new scenarios, task 4.6, stale-reference cleanup) in exchange for eliminating the last substantive category of security ambiguity. The streaming vs. buffering distinction would have been a real CVE-class bug if shipped as-is under codex's catch.
- Accepted the `$ref` exception-type nit as deferred rather than spending another round on it. Exception taxonomy is more naturally decided when writing the parser, not when specifying it.
- Accepted stopping at round 2 rather than running round 3. Round-1 → round-2 regression ratio (findings introduced by fixes, divided by findings addressed) was 3/10 = 30%; projecting forward suggests round-3 would surface 1–2 low-criticality regressions at most — below the autopilot threshold for an additional round.

### Open Questions

- [ ] Will `httpx.Response.aiter_bytes` be available with the pinned `httpx` version? (Almost certainly yes — it has been stable since httpx 0.11; our pin is much newer. Verify in implementation.)
- [ ] Does pytest-httpserver support the "delayed response" used in task 6.4's timeout test? (Yes, via `respond_with_handler` with an explicit `time.sleep`. Noting here so implementors don't rediscover.)
- [ ] Should the 10 MiB cap be persona-configurable in a future phase, or is it a hard-coded security invariant? Left for P9 `error-resilience` to decide.

### Context

Iteration 3 addressed the Round 2 multi-vendor plan review. Three vendors dispatched in parallel (claude, codex gpt-5.5, gemini) produced 19 raw findings — a 41% reduction from round 1. Ten substantive issues addressed, three accepted with documented rationale. The most consequential fix was R2-C5 (streaming enforcement of the 10 MiB cap), which would have been a real security regression had it shipped. Multi-vendor review caught three iteration-2-introduced regressions (R2-C1, R2-C2, R2-C4) that a single-vendor pass would have missed. `openspec validate --strict` green. Transitioning PLAN_REVIEW → IMPLEMENT per the autopilot state machine.
