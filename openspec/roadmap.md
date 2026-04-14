# agentic-assistant — OpenSpec Roadmap v2

> **Supersedes** the original roadmap derived solely from
> `docs/agentic-assistant-bootstrap-v4.1.md`. This v2 integrates perplexity
> review feedback (`docs/perplexity-feedback.md`) and reorders phases per
> §8 "Recommended Implementation Order." The original roadmap is preserved
> in git history.
>
> Change that introduced this rewrite: `roadmap-v2-perplexity-integration`.

## Guiding principles

1. **One OpenSpec proposal per §8 item** — fine-grained, independently
   reviewable, each eligible for `/plan-feature` → `/autopilot`.
2. **§8 ordering is authoritative** — even where the original roadmap
   had a different order. The only exception: `P1.5 bootstrap-fixes`
   runs first to clear hygiene debt before architectural work starts.
3. **Old P2–P10 items without perplexity coverage are folded in at the
   end** so no prior scope is silently dropped.
4. **Docs — not CI — enforce the DAG**. Consult this file before
   invoking `/plan-feature` or `/autopilot` for any phase.

## Proposal sequence

| # | Change ID | Status | Perplexity § | Source | Description |
|---|-----------|--------|--------------|--------|-------------|
| P1 | `bootstrap-vertical-slice` | **archived** (2026-04-12) | — | original P1 | Core library + Deep Agents harness + CLI + 5 roles + personal persona + delegation + tests + CI |
| P1.5 | `bootstrap-fixes` | pending | §7.1–§7.5 | perplexity §7 | CLI `-h` flag conflict; add `sqlalchemy.text()` wrapper; reconcile `deepagents` package reference; add `[project.scripts]` entry point; fix `name` variable shadowing in `PersonaRegistry.load` |
| P1.7 | `harness-advisor-extension` | pending | — | new (April 2026 Anthropic advisor tool) | Extend `HarnessAdapter` with `advise()` alongside `invoke()` / `spawn_sub_agent()`; Deep Agents impl wires the `advisor_20260301` tool type + `anthropic-beta: advisor-tool-2026-03-01` header; add `advisor:` block to `RoleConfig` schema (model, trigger, max_calls_per_task, budget_tokens); new `core/advisor.py` `AdvisorClient` (kept separate from `DelegationSpawner` — shared context vs fresh, guidance vs work); MS Agent Framework harness documents emulated-fallback behavior; opt-in per role, no default behavior change. Rationale: executor-advisor pattern ([blog](https://claude.com/blog/the-advisor-strategy)) — downshift `coder`/similar single-loop roles from Opus to Sonnet with an Opus advisor for ~12% cost reduction + quality bump; must land before P2 so memory-architecture retrieval paths can opt in from day one |
| P2 | `memory-architecture` | pending | §1.2, §8.1 | perplexity §8.1 + old P3 | `core/memory.py` MemoryManager + `core/graphiti.py` client factory + per-persona AsyncEngine + `memory`/`preferences`/`interactions` tables + `scripts/export-memory.sh` that regenerates `memory.md` from Postgres+Graphiti |
| P3 | `http-tools-layer` | pending | §8.2 | perplexity §8.2 + old P2 | `src/assistant/http_tools/` — `/help`-based discovery, `_build_tool()` Pydantic-model + async-callable generator, auth header handling, registry, `--list-tools` CLI command, integration tests against mock server |
| P4 | `observability` | pending | §1.1, §8.3 | perplexity §8.3 (new) | `core/observability.py` — `@traced` decorator, spans on `HarnessAdapter.invoke()` and `DelegationSpawner.delegate()`, token + latency + cost tracking per persona/role. Langfuse backend default; OpenLLMetry adapter optional |
| P5 | `ms-graph-extension` | pending | §8.4 | perplexity §8.4 + old P5 | Real `ms_graph`, `teams`, `sharepoint`, `outlook` extensions (replaces P1 stubs). MSAL auth, httpx client, OAuth refresh. Full MS Agent Framework harness implementation replacing P1's `NotImplementedError` stub |
| P6 | `a2a-server` | pending | §6, §8.5 | perplexity §8.5 (new; was Phase-16 "out of scope") | `src/assistant/a2a/` — server.py, task_handler.py, agent_card.py. Exposes `/a2a/v1/message:stream` endpoint. Serves `.well-known/agent.json`. Lets Copilot Studio Chief of Staff delegate to this assistant |
| P7 | `scheduler` | pending | §2.1, §8.6 | perplexity §8.6 (new) | `core/scheduler.py` — cron (croniter) + calendar-event + polling triggers. `schedules:` section in `persona.yaml`. `--daemon` CLI flag. Morning briefing / email triage / pre-meeting brief hooks |
| P8 | `obsidian-vault` | pending | §2.2, §8.7 | perplexity §8.7 (new) | Obsidian vault RAG integration. Preferred: add indexing endpoint to `agentic-content-analyzer` and reference it as a tool source. Fallback: standalone `extensions/obsidian.py` with wikilink parsing, pgvector index |
| P9 | `error-resilience` | pending | §1.3, §8.8 | perplexity §8.8 (new) | `core/resilience.py` — `tenacity`-based retry on transient HTTP failures, circuit breaker per backend, graceful degradation (agent notes unavailability instead of silent omission). Applied to http_tools client + extension `health_check()` |
| P10 | `extension-lifecycle` | pending | §3.1, §8.9 | perplexity §8.9 (new) | Extend `Extension` protocol with `initialize()`, `shutdown()`, `refresh_credentials()` lifecycle hooks. `PersonaRegistry.load_extensions()` calls `initialize()` post-load; registers shutdown handler |
| P11 | `harness-routing` | pending | §3.2, §8.10 | perplexity §8.10 (new) | Dynamic harness selection in `harnesses/factory.py`. `--harness auto` default. Routes M365-tool tasks → MS Agent Framework, complex reasoning → Deep Agents |
| P12 | `delegation-context` | pending | §3.3, §8.11 | perplexity §8.11 + old P8 | `DelegationContext` dataclass (parent_role, delegation_chain, memory_snippets, conversation_summary, constraints). Cycle detection. `delegate_parallel`. Monitoring/cancellation. Delegation analytics tables |
| P13 | `security-hardening` | pending | §4, §8.12 | perplexity §8.12 (new) | Per-persona env var scoping in `_env()` helper. Per-persona `.env` files. Extension `manifest.yaml` with SHA-256 hashes verified before `spec.loader.exec_module()` |
| P14 | `google-extensions` | pending | — | original P4 | Real `gmail`, `gcal`, `gdrive` extension implementations. OAuth refresh via the P10 lifecycle hooks |
| P15 | `work-persona-config` | pending | — | original P6 | Create `assistant-config-work` submodule, wire into `.gitmodules`, populate work persona config + role overrides. Deferred until work machine available |
| P16 | `cli-harness-integrations` | pending | — | original P7 | Deeper Claude Code / Codex / Gemini integrations — slash commands in `.claude/commands/`, `.codex/skills/`, `.gemini/settings.json`. Persona-aware routing |
| P17 | `mcp-server-exposure` | pending | — | original P9 | Expose the assistant as an MCP server so other Claude Code sessions can invoke it as a tool. Complementary to P6 A2A (different protocols, different clients) |
| P18 | `railway-deployment` | pending | — | original P10 | Run persona instances as Railway services + deployment manifests |

## Status lifecycle

Each phase transitions: `pending` → `in-progress` (when `/plan-feature`
creates its proposal directory) → `archived` (when
`/openspec-archive-change` finalizes it). This table is the canonical
record — update it as part of the phase's final commit.

## Dependency graph

```
P1 (archived)
 └─→ P1.5 bootstrap-fixes (hygiene; unblocks everything below)
      └─→ P1.7 harness-advisor-extension (HarnessAdapter.advise(); must land before P2 so downstream phases opt in from day one)
           ├─→ P2 memory-architecture ──┬─→ P7 scheduler
           │                            ├─→ P8 obsidian-vault
           │                            └─→ P12 delegation-context
           ├─→ P3 http-tools-layer ─────┬─→ P5 ms-graph-extension ──┬─→ P6 a2a-server
           │                            │                          └─→ P14 google-extensions
           │                            └─→ P9 error-resilience
           ├─→ P4 observability (spans everything below — lands early; adds advisor-call span type + cost attribution)
           ├─→ P10 extension-lifecycle ─→ P13 security-hardening
           └─→ P11 harness-routing (needs P5 MS Agent Framework real + P1.7 advisor primitive; advisor-capable roles prefer Deep Agents)

P15 work-persona-config — independent; triggered by machine availability; needs P5 + P8
P16 cli-harness-integrations — independent; needs P1.5
P17 mcp-server-exposure — needs P6 (protocol parallel)
P18 railway-deployment — needs P15, P16
```

## Phase-by-phase execution via autopilot

Per phase:

```bash
# 1. Plan
/plan-feature <change-id>   # e.g. memory-architecture

# 2. Implement (once plan approved at Gate 2)
/autopilot <change-id>

# 3. Archive
/openspec-archive-change <change-id>

# 4. Update this roadmap's status column
```

The change-ids in this roadmap ARE the OpenSpec change-ids. Do not
re-prefix with dates; the roadmap is the identity source.

## Cross-cutting themes

| Theme | Phases that touch it |
|-------|----------------------|
| **Memory hierarchy** (memory.md derived from Postgres+Graphiti — perplexity §1.2) | P2 establishes; P7/P8/P12 consume |
| **Observability** (tracing, cost per persona×role — §1.1) | P4 establishes; all later phases add spans to their new code paths |
| **Resilience** (retry, circuit breaker — §1.3) | P9 establishes; P3/P5/P14/P17 adopt |
| **Security boundaries** (credential scoping, manifest validation — §4) | P13 establishes; all phases loading config must comply |
| **Proactive execution** (scheduler + A2A + Obsidian RAG — §2) | P6/P7/P8 — the differentiated Chief-of-Staff story |
| **Executor-advisor pattern** (cheap executor + on-tap Opus advisor — April 2026 Anthropic tool) | P1.7 establishes `advise()`; P4 adds span + cost attribution; P11 routes advisor-capable roles to Deep Agents; individual roles opt in via `advisor:` block in `role.yaml` |

## Out of scope for roadmap v2

Items from bootstrap spec Phase 16 not adopted by perplexity §8 and
still deferred: cross-persona bridge, multi-model routing (beyond the
harness-routing in P11), role learning, persona config encryption,
NotebookLM integration. Each may re-enter a future v3 roadmap if
perplexity-equivalent review surfaces demand.
