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
2. **§8 ordering is informational, not a hard constraint** — adopted
   as the default ordering where the original roadmap had a different
   order. The **Dependency graph** below represents real functional
   prerequisites; phases shown as siblings have no functional coupling
   and MAY run in any order. `P1.7 bootstrap-fixes` is a functional
   prerequisite for a handful of phases (explicitly noted in the
   graph), not a global gate. (P1.5 / P1.6 are hygiene / spec-sync
   rows that already shipped before bootstrap-fixes was planned.)
3. **Old P2–P10 items without perplexity coverage are folded in at the
   end** so no prior scope is silently dropped.
4. **Docs — not CI — enforce the DAG**. Consult this file before
   invoking `/plan-feature` or `/autopilot` for any phase.

## Proposal sequence

| # | Change ID | Kind | Status | Perplexity § | Source | Description |
|---|-----------|------|--------|--------------|--------|-------------|
| P1 | `bootstrap-vertical-slice` | phase | **archived** (2026-04-12) | — | original P1 | Core library + Deep Agents harness + CLI + 5 roles + personal persona + delegation + tests + CI |
| P1.5 | `test-privacy-boundary` | phase | **archived** (2026-04-13) | — | new (IR hygiene from P1 validation) | Separate public tests from private persona data: two-layer (collection-time substring scan + runtime FS patching) boundary guard, `ASSISTANT_PERSONAS_DIR` env-var contract, `scripts/push-with-submodule.sh` atomic dual-commit push wrapper |
| P1.6 | `sync-test-privacy-boundary-spec` | non-phase (spec-sync) | **archived** (2026-04-13) | — | spec-sync follow-up of P1.5 | Listed for chronological context. Spec-only change that codified five drift items found during P1.5 validation (env-var contract, subprocess `executable=`/`cwd=` kwarg coverage, hygiene-test exclusion list, submodule `parents[N]` abstraction, atomic-push wrapper requirement) |
| P1.7 | `bootstrap-fixes` | phase | pending | §7.1–§7.5 | perplexity §7 | CLI `-h` flag conflict; add `sqlalchemy.text()` wrapper; reconcile `deepagents` package reference; add `[project.scripts]` entry point; fix `name` variable shadowing in `PersonaRegistry.load` |
| P1.8 | `capability-protocols` | phase | **archived** (2026-04-20) | — | new (harness architecture redesign) | Five capability protocols (GuardrailProvider, SandboxProvider, MemoryPolicy, ToolPolicy, ContextProvider) + CapabilityResolver + two-tier harness split (SDK vs Host) + ClaudeCodeHarness + CLI export subcommand + delegation guardrail integration |
| P2 | `memory-architecture` | phase | pending | §1.2, §8.1 | perplexity §8.1 + old P3 | `core/memory.py` MemoryManager + `core/graphiti.py` client factory + per-persona AsyncEngine + `memory`/`preferences`/`interactions` tables + `scripts/export-memory.sh` that regenerates `memory.md` from Postgres+Graphiti. Implements `MemoryPolicy` protocol from P1.8 |
| P3 | `http-tools-layer` | phase | pending | §8.2 | perplexity §8.2 + old P2 | `src/assistant/http_tools/` — `/help`-based discovery, `_build_tool()` Pydantic-model + async-callable generator, auth header handling, registry, `--list-tools` CLI command, integration tests against mock server |
| P4 | `observability` | phase | pending | §1.1, §8.3 | perplexity §8.3 (new) | `core/observability.py` — `@traced` decorator, spans on `HarnessAdapter.invoke()` and `DelegationSpawner.delegate()`, token + latency + cost tracking per persona/role. Langfuse backend default; OpenLLMetry adapter optional |
| P5 | `ms-graph-extension` | phase | pending | §8.4 | perplexity §8.4 + old P5 | Real `ms_graph`, `teams`, `sharepoint`, `outlook` extensions (replaces P1 stubs). MSAL auth, httpx client, OAuth refresh. Full MS Agent Framework harness implementation replacing P1's `NotImplementedError` stub |
| P6 | `a2a-server` | phase | pending | §6, §8.5 | perplexity §8.5 (new; was Phase-16 "out of scope") | `src/assistant/a2a/` — server.py, task_handler.py, agent_card.py. Exposes `/a2a/v1/message:stream` endpoint. Serves `.well-known/agent.json`. Lets Copilot Studio Chief of Staff delegate to this assistant |
| P7 | `scheduler` | phase | pending | §2.1, §8.6 | perplexity §8.6 (new) | `core/scheduler.py` — cron (croniter) + calendar-event + polling triggers. `schedules:` section in `persona.yaml`. `--daemon` CLI flag. Morning briefing / email triage / pre-meeting brief hooks |
| P8 | `obsidian-vault` | phase | pending | §2.2, §8.7 | perplexity §8.7 (new) | Bi-directional Obsidian vault sync, split by authoring domain. Vault config declares `notes_dir` (human-authored: frameworks, meeting notes, raw thoughts — synced **into** ACA as indexed source) and `agent_dir` (agent-authored: entity hub pages, compiled summaries — rendered **from** ACA; frontmatter declares `agent_maintained: true`, `compiled_from: <entity_id>`, `regenerated_at: <ts>`; hand-edits may be overwritten on regeneration). Preferred: two endpoints on `agentic-content-analyzer` (`/index/vault-notes` for inbound, `/render/agent-folder` for outbound) invoked by a persona extension. Fallback: standalone `extensions/obsidian.py` with wikilink parsing + pgvector index covers the `notes_dir → ACA` direction only; `agent_dir` rendering deferred until ACA endpoint exists. Headless personas (no vault) skip both directions without penalty. Doctrine/frameworks remain in the persona submodule (loaded via P1.8 `ContextProvider`) — explicitly **not** vault content. |
| P9 | `error-resilience` | phase | pending | §1.3, §8.8 | perplexity §8.8 (new) | `core/resilience.py` — `tenacity`-based retry on transient HTTP failures, circuit breaker per backend, graceful degradation (agent notes unavailability instead of silent omission). Applied to http_tools client + extension `health_check()` |
| P10 | `extension-lifecycle` | phase | pending | §3.1, §8.9 | perplexity §8.9 (new) | Extend `Extension` protocol with `initialize()`, `shutdown()`, `refresh_credentials()` lifecycle hooks. `PersonaRegistry.load_extensions()` calls `initialize()` post-load; registers shutdown handler |
| P11 | `harness-routing` | phase | pending | §3.2, §8.10 | perplexity §8.10 (new) | Dynamic harness selection in `harnesses/factory.py`. `--harness auto` default. Routes M365-tool tasks → MS Agent Framework, complex reasoning → Deep Agents |
| P12 | `delegation-context` | phase | pending | §3.3, §5 P1, §8.11 | perplexity §8.11 + old P8 + §5 P1 router | `DelegationContext` dataclass (parent_role, delegation_chain, memory_snippets, conversation_summary, constraints). Cycle detection. `delegate_parallel`. Monitoring/cancellation. Delegation analytics tables. **Includes `delegation/router.py` intent-classification logic** for automatic delegation routing (perplexity §5 P1 item; was missing from v2 scope) |
| P13 | `security-hardening` | phase | pending | §4, §8.12 | perplexity §8.12 (new) | Per-persona env var scoping in `_env()` helper. Per-persona `.env` files. Extension `manifest.yaml` with SHA-256 hashes verified before `spec.loader.exec_module()` |
| P14 | `google-extensions` | phase | pending | — | original P4 | Real `gmail`, `gcal`, `gdrive` extension implementations. OAuth refresh via the P10 lifecycle hooks |
| P15 | `work-persona-config` | phase | pending | — | original P6 | Create `assistant-config-work` submodule, wire into `.gitmodules`, populate work persona config + role overrides. Deferred until work machine available |
| P16 | `cli-harness-integrations` | phase | pending | — | original P7 | Deeper Claude Code / Codex / Gemini integrations — slash commands in `.claude/commands/`, `.codex/skills/`, `.gemini/settings.json`. Persona-aware routing |
| P17 | `mcp-server-exposure` | phase | pending | — | original P9 | Expose the assistant as an MCP server so other Claude Code sessions can invoke it as a tool. Complementary to P6 A2A (different protocols, different clients) |
| P18 | `railway-deployment` | phase | pending | — | original P10 | Run persona instances as Railway services + deployment manifests |
| X1 | `add-teacher-role` | non-phase (feature) | pending | — | user-requested (2026-04-16) | Add `teacher` role with Feynman + Socratic skill files; `--method` CLI flag and `/method` / `/methods` REPL commands; forward-declare `content_analyzer:*` preferred tools for post-P3 wiring. Independent of the P-phase DAG — does not block or depend on any phase. |

## Status lifecycle

Each phase transitions: `pending` → `in-progress` (when `/plan-feature`
creates its proposal directory) → `archived` (when
`/openspec-archive-change` finalizes it). This table is the canonical
record — update it as part of the phase's final commit.

## Dependency graph

Edges represent **functional prerequisites** — phase B depends on a
concrete output of phase A — not chronological or stylistic preference.
Phases drawn as siblings have no functional dependency on each other
and MAY run in any order.

```
P1 bootstrap-vertical-slice (archived)
 │
 ├─→ P1.5 test-privacy-boundary (archived; tests/ infrastructure)
 │    └─→ P1.6 sync-test-privacy-boundary-spec (archived; spec-sync of P1.5)
 │
 ├─→ P1.7 bootstrap-fixes (pending; §7 hygiene)
 │    ├─→ P3 http-tools-layer                (needs §7.1 CLI `-h` fix; §7.4 entry point)
 │    └─→ P11 harness-routing                (needs §7.3 deepagents package reference reconciled)
 │
 ├─→ P1.8 capability-protocols (pending; harness architecture redesign)
 │    ├─→ P2 memory-architecture             (implements MemoryPolicy protocol;
 │    │                                       also needs P1.7 §7.2 sqlalchemy.text() wrapper)
 │    ├─→ P3 http-tools-layer                (implements ToolPolicy source;
 │    │                                       also needs P1.7 §7.1 + §7.4)
 │    ├─→ P11 harness-routing                (three-tier routing uses CapabilityResolver;
 │    │                                       also needs P1.7 §7.3)
 │    ├─→ P13 security-hardening             (implements GuardrailProvider;
 │    │                                       also needs P10 lifecycle hooks)
 │    └─→ P16 cli-harness-integrations       (extends HostHarnessAdapter exports;
 │                                            also needs P1.7 §7.1 + §7.4)
 │
 ├─→ P4 observability                        (independent of P1.7/P1.8; lands early for tracing)
 ├─→ P10 extension-lifecycle                 (independent of P1.7/P1.8; initialize/shutdown hooks)
 │
 ├─→ P2 memory-architecture ──┬─→ P7 scheduler         (needs memory for briefings)
 │                            ├─→ P8 obsidian-vault    (needs memory for indexing backend)
 │                            └─→ P12 delegation-context  (needs memory for context snippets;
 │                                                        scope includes delegation/router.py
 │                                                        intent classification per §5 P1)
 │
 ├─→ P3 http-tools-layer ─────┬─→ P5 ms-graph-extension ──┬─→ P6 a2a-server           (exposes assistant via A2A)
 │                            │                          └─→ P14 google-extensions    (gmail/gcal/gdrive)
 │                            └─→ P9 error-resilience     (retries applied to http_tools client)
 │
 ├─→ P10 extension-lifecycle ─→ P13 security-hardening  (manifest validation uses lifecycle hook)
 └─→ P5 ms-graph-extension    ─→ P11 harness-routing    (routes M365 tasks once MS Agent Framework is real)

# Independent / long-range
P15 work-persona-config       needs P5 + P8; also triggered by machine availability
P17 mcp-server-exposure       needs P6 (protocol parallel; A2A and MCP expose the same assistant)
P18 railway-deployment        needs P15, P16
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
| **Capability protocols** (guardrails, sandbox, memory policy, tool policy — harness architecture) | P1.8 establishes protocols; P2 implements MemoryPolicy; P3 implements ToolPolicy; P13 implements GuardrailProvider; P11/P16 consume CapabilityResolver |
| **Memory hierarchy** (memory.md derived from Postgres+Graphiti — perplexity §1.2) | P2 establishes; P7/P8/P12 consume |
| **Observability** (tracing, cost per persona×role — §1.1) | P4 establishes; all later phases add spans to their new code paths |
| **Resilience** (retry, circuit breaker — §1.3) | P9 establishes; P3/P5/P14/P17 adopt |
| **Security boundaries** (credential scoping, manifest validation — §4) | P13 establishes; all phases loading config must comply |
| **Proactive execution** (scheduler + A2A + Obsidian RAG — §2) | P6/P7/P8 — the differentiated Chief-of-Staff story |

## Out of scope for roadmap v2

Items from bootstrap spec Phase 16 not adopted by perplexity §8 and
still deferred: cross-persona bridge, multi-model routing (beyond the
harness-routing in P11), role learning, persona config encryption,
NotebookLM integration. Each may re-enter a future v3 roadmap if
perplexity-equivalent review surfaces demand.
