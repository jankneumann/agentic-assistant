# Observability Layer

**Change ID**: `observability`
**Roadmap Phase**: 7 (item_id: `observability`)
**Effort**: L (upgraded from M at planning gate after scope expansion — see Selected Approach)
**Depends on**: `bootstrap-vertical-slice` (completed)
**Blocks**: downstream phases that benefit from span coverage on their new code paths (`ms-graph-extension`, `google-extensions`, `a2a-server`, `scheduler`, `mcp-server-exposure`, `delegation-context`)

## Why

Agent workloads in this repo emit LLM calls, spawn sub-agents via delegation, read/write memory, query Graphiti, and invoke both Python-native extension tools and HTTP OpenAPI-discovered tools. Today none of this is traced:

- **No cost attribution**: we cannot answer "which persona × role is spending tokens" — critical as personas (work, personal) diverge and roles proliferate.
- **No delegation-chain diagnostics**: sub-agent invocations are opaque; when a delegated run stalls, there is no span tree to inspect.
- **No per-operation latency view**: memory recalls, Graphiti queries, and HTTP-tool calls all execute under `logging.getLogger(__name__)` with no timing or correlation IDs.
- **Future-phase opacity**: every downstream phase (`ms-graph-extension`, `google-extensions`, `a2a-server`, `mcp-server-exposure`) adds new invocation paths. Landing observability first means those phases add spans as they're written, rather than retrofitting after.

This change lands the tracing substrate. It does **not** add dashboards, alerting, or analysis pipelines — those are downstream of having the data.

Cross-references:
- Perplexity §1.1 (observability is the missing instrumentation layer for agent workloads)
- Perplexity §8.3 (cost tracking per persona × role)
- Cross-repo lessons: `~/.claude/projects/-Users-jankneumann-Coding-agentic-assistant/memory/reference_langfuse_lessons.md`
- Reference implementation: `~/Coding/agentic-newsletter-aggregator/src/telemetry/` and `openspec/specs/observability/`

## What Changes

### New module: `src/assistant/telemetry/`

- `providers/base.py` — `ObservabilityProvider` Protocol (`runtime_checkable`) with methods:
  - `name` (property)
  - `setup(app=None) -> None` — provider init, called once at app startup
  - `trace_llm_call(*, model, persona, role, messages, input_tokens, output_tokens, duration_ms, metadata=None) -> None` — harness invocation
  - `trace_delegation(*, parent_role, sub_role, task, persona, duration_ms, outcome, metadata=None) -> None` — delegation hop
  - `trace_tool_call(*, tool_name, tool_kind, persona, role, duration_ms, error=None, metadata=None) -> None` — extension + http-tool invocation (shared)
  - `trace_memory_op(*, op, target, persona, duration_ms, metadata=None) -> None` — memory + graphiti operations (shared)
  - `start_span(name, attributes=None) -> contextmanager` — generic escape hatch
  - `flush() -> None` / `shutdown() -> None`
- `providers/noop.py` — zero-cost no-op implementation (default when disabled)
- `providers/langfuse.py` — Langfuse native SDK provider (lazy import)
- `factory.py` — `get_observability_provider()` with 3-level graceful degradation:
  1. `LANGFUSE_ENABLED=false` / no-key → noop, zero overhead
  2. `ImportError` on `langfuse` → log warn, return noop
  3. Provider init raises → log warn, return noop
- `flush_hook.py` — registers `atexit.register(provider.shutdown)` unless `LANGFUSE_FLUSH_MODE=per_op` is set, in which case each `trace_*` method flushes inline
- `sanitize.py` — secret-redaction regexes, ordered most-specific-first; includes private-submodule-URL patterns on top of the Langfuse/generic set

### Hook integrations

- `src/assistant/harnesses/base.py` and `src/assistant/harnesses/deep_agents.py` — wrap `invoke()` with a `@traced_harness` decorator that calls `provider.trace_llm_call(...)` with persona/role/token-count context
- `src/assistant/delegation/spawner.py` — wrap `delegate()` with `@traced_delegation` decorator at line 33; span parent_role → sub_role with task hash
- `src/assistant/core/memory.py` — instrument `MemoryStore` read/write/recall via `trace_memory_op`
- `src/assistant/core/graphiti.py` — instrument `add_episode` / query methods via `trace_memory_op`
- `src/assistant/extensions/_base.py` (or equivalent base) — wrap `as_langchain_tools()` so every returned `StructuredTool` has `trace_tool_call` invoked on `_run`/`_arun`. Extension stubs return `[]` today but the wrapping is in place, so real impls in `ms-graph-extension`/`google-extensions` get traced for free.
- `src/assistant/http_tools/builder.py` — wrap HTTP-tool invocations with `trace_tool_call(tool_kind='http')`

### Config loading

- Add `LANGFUSE_*` env-var reads to a new `telemetry/config.py` dataclass (mirrors pydantic BaseSettings pattern from newsletter-aggregator but uses the repo's existing `_env()` helper from `persona.py` to stay consistent with the project's [secrets management pattern](../../../docs/gotchas.md#secrets)):
  - `LANGFUSE_ENABLED` (default `false`)
  - `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
  - `LANGFUSE_ENVIRONMENT` (defaults to `os.getenv("ASSISTANT_PROFILE", "local")`)
  - `LANGFUSE_FLUSH_MODE` (default `shutdown`, alt `per_op`)
  - `LANGFUSE_SAMPLE_RATE` (default 1.0)

### Dev infrastructure

- `docker-compose.langfuse.yml` at repo root — self-hosted Langfuse v3 stack (Postgres 17, ClickHouse, Redis, MinIO, langfuse-web on 3100, langfuse-worker). **Includes `LANGFUSE_INIT_*` env vars** (org/project/user/keys auto-provisioned) — fixes the gap the reference lessons flagged as a newsletter-aggregator follow-up. Separate compose file with its own project (`-p langfuse`) — avoids profile-flag amnesia and isolates ClickHouse migrations from app Postgres.
- `docs/observability.md` — quickstart: `docker-compose -f docker-compose.langfuse.yml -p langfuse up -d`, then `LANGFUSE_ENABLED=true` in the runtime env.

### Claude Code Stop hook (optional, env-driven)

- Document how to wire the existing repo-agnostic hook from `~/Coding/agentic-coding-tools/agent-coordinator/scripts/langfuse_hook.py` via `~/.claude/settings.json` env vars. **No code change in this repo** — pointer only. This adds Claude-Code-level session traces alongside the in-app spans.

### Dependencies

- Add `langfuse>=3.0,<4.0` to `pyproject.toml` as an optional dependency under a `telemetry` extra. Default install remains trace-free; `uv sync --extra telemetry` opts in.

### Tests

- `tests/telemetry/test_protocol.py` — Protocol methods, noop no-op behavior
- `tests/telemetry/test_factory.py` — 3-level degradation, including `patch("builtins.__import__", side_effect=ImportError(...))` (pattern from newsletter-aggregator `tests/telemetry/test_langfuse_provider.py:155`)
- `tests/telemetry/test_langfuse.py` — lazy-import, sanitize integration, flush mode switch
- `tests/telemetry/test_integrations.py` — integration tests on harness/delegation/memory/graphiti/tool-call hooks using noop + assert-emission pattern (no real Langfuse calls in CI)
- Honor privacy boundary: tests use fixture personas and assert sentinel `FIXTURE_PERSONA_SENTINEL_v1` is never emitted to telemetry (span attributes are sanitized)

## Impact

### Affected specs
- New spec: `observability` capability
- Modified specs (hook integration clauses):
  - `harness-adapter` — adds SHALL clause: emits `trace_llm_call` on `invoke()`; adds scenario covering the `MSAgentFrameworkHarness` stub's traced-on-raise behavior
  - `delegation-spawner` — adds SHALL clause: emits `trace_delegation` on `delegate()` with 256-character hashing threshold named in the Requirement body
  - `extension-registry` — adds SHALL clause: extension tool calls traced via `trace_tool_call`; authoritative aggregation-site list lives in the new `capability-resolver` delta
  - `capability-resolver` — adds SHALL clause naming the two extension-tool aggregation sites (`core/capabilities/tools.py` and `harnesses/sdk/deep_agents.py`) and the shared `wrap_extension_tools` helper
  - `http-tools` — adds SHALL clause: http-tool invocations traced via `trace_tool_call`, with sanitization cross-referenced to observability's Secret Sanitization Requirement
  - (Memory spec not yet populated pending `memory-architecture` phase; `trace_memory_op` lands as a scenario in the new `observability` spec and is cross-referenced when memory-architecture archives.)

### Affected code
- New: `src/assistant/telemetry/` (module)
- Instrumented: `src/assistant/harnesses/`, `src/assistant/delegation/`, `src/assistant/core/memory.py`, `src/assistant/core/graphiti.py`, `src/assistant/extensions/_base.py`, `src/assistant/http_tools/builder.py`
- New: `docker-compose.langfuse.yml`, `docs/observability.md`
- Modified: `pyproject.toml` (telemetry extra)

### Test impact
- New test directory: `tests/telemetry/`
- Extensions to integration tests that exercise harness + delegation paths (assert span emission via noop capture)

### Risk surface
- **Performance**: decorator overhead on every harness/delegation/memory call. Noop path must be zero-allocation (verified in `test_protocol.py` by microbenchmark sanity check).
- **Privacy**: span attributes include `persona` and `role` names — which may be private config names. Sanitization pass strips any value matching private-submodule-URL regex; `persona` fields pass-through but `metadata` is sanitized.
- **Dep conflict**: Langfuse transitively depends on `httpx` — already in deps for http-tools-layer. No conflict expected; verify via `uv sync --extra telemetry` in CI.

## Approaches Considered

### Approach A: Native Langfuse SDK + extended Protocol with first-class trace methods **(Recommended)**

`src/assistant/telemetry/` module with `ObservabilityProvider` Protocol carrying four first-class methods (`trace_llm_call`, `trace_delegation`, `trace_tool_call`, `trace_memory_op`) plus a generic `start_span` escape hatch. Native Langfuse SDK provider with 3-level graceful degradation at the factory layer. `atexit`-based shutdown-flush by default; `LANGFUSE_FLUSH_MODE=per_op` for debugging. Full hook coverage across harness, delegation, memory, graphiti, extensions, http_tools.

- **Pros**:
  - Each concern is a named Protocol method → providers have enforced attribute contracts, can't accidentally drop persona/role from llm calls or parent/sub role from delegation. Clearer code at call sites: `provider.trace_delegation(parent_role=..., sub_role=..., task=...)` vs `provider.start_span("delegation", {"parent": ...})`.
  - Consolidates memory + graphiti under `trace_memory_op` and extensions + http_tools under `trace_tool_call` — symmetric and keeps the Protocol surface small (5 methods).
  - Mirrors the mature newsletter-aggregator pattern (Protocol + factory + providers) while adapting to agent-shaped concerns.
  - Native SDK gives persona/role → session/user mapping, which OTel bridge cannot express.
  - Shutdown-only flush avoids the latency spike documented in the memory lesson file.
  - Full hook coverage means downstream phases (ms-graph, google, mcp-server) don't need to re-plan observability per phase.
- **Cons**:
  - Protocol surface (5 methods) is larger than the newsletter reference (3 methods). Providers other than langfuse/noop have slightly more to implement.
  - Scope is effectively `L`, not `M` — the user's "all four extra hooks" answer expands coverage. Additional instrumentation sites, additional tests.
  - Requires mild discipline from downstream phase authors to use the right `trace_*` method for their hook.
- **Effort**: L

### Approach B: Literal newsletter-aggregator Protocol copy (only `trace_llm_call` + `start_span`)

Directly copy `ObservabilityProvider` from newsletter-aggregator as-is. Harness uses `trace_llm_call`; delegation/memory/graphiti/tool-calls all use generic `start_span(name, attrs)` context manager.

- **Pros**:
  - Maximum pattern reuse — can literally copy the file and rename the module.
  - Smaller Protocol surface (3 methods).
  - Easier to bring an OTel adapter later — `start_span` maps 1:1 to OTel spans.
- **Cons**:
  - Delegation/memory/tool-call semantics live in stringly-typed `attrs` dict — no type safety, easy to forget `parent_role` or `sub_role`.
  - Per-request flush in newsletter's `trace_llm_call` contradicts the shutdown-only preference chosen at Q2 — would need to fork the implementation anyway.
  - Agent-specific concepts (delegation chains, persona×role cost attribution) are second-class.
- **Effort**: M-L (less Protocol work, same amount of hook wiring)

### Approach C: Minimal Protocol — only `start_span`

Drop named trace methods entirely. Every hook emits `start_span(name, attrs)`. Provider decides internally how to translate span names into backend-specific concepts (Langfuse sessions, OTel spans, etc.).

- **Pros**:
  - Simplest possible Protocol (1 method + lifecycle).
  - Perfectly portable — literally just OTel spans.
  - Easy to add new hook kinds later (just pick a span name).
- **Cons**:
  - No enforced attribute contract — persona/role/token-count attrs get set ad-hoc at each call site, drift is inevitable across the 6+ hook points.
  - Loses Langfuse's specialized `trace_llm_call` semantics (message-aware rendering in the UI, generation vs span distinction).
  - Cost attribution requires manual aggregation in the backend rather than being first-class in the Protocol.
- **Effort**: M

### Recommendation

**Approach A**. User answers at Q1 explicitly selected "extend with first-class methods", and Q3's "all four extra scopes" answer means the Protocol will see 6+ distinct hook call-sites — the per-site type safety of named methods pays for itself at this coverage level. Q2's shutdown-only preference rules out a literal newsletter copy anyway (Approach B would need to fork that behavior), and Approach C's minimal surface fights the Langfuse-native semantics we chose as the default provider.

---

## Selected Approach

**Approach A — Native Langfuse SDK + extended Protocol with first-class trace methods** (selected at Gate 1, 2026-04-24).

Rationale:
- User Q1 answer explicitly selected "extend with first-class methods" over literal newsletter copy or minimal-span approach.
- User Q2 answer selected shutdown-only flush with `LANGFUSE_FLUSH_MODE=per_op` env override — rules out Approach B's inherited per-request-flush behavior.
- User Q3 answer expanded scope to all four extra hooks (memory, graphiti, extensions, http_tools) — making the Protocol's typed-attribute enforcement more valuable at 6+ call-sites.
- Effort upgraded from roadmap-declared M to L and explicitly accepted at Gate 1.

Approaches B and C are recorded above for posterity; neither is being pursued.
