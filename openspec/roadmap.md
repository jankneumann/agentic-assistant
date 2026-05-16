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
| P1.7 | `bootstrap-fixes` | phase | **archived** (2026-04-20) | §7.1–§7.5 | perplexity §7 | All items resolved: §7.1 CLI `-H` fix landed in P1; §7.3 `deepagents` v0.5.2 confirmed valid; §7.4 entry point landed in P1; §7.5 `src_name` fix landed in P1. §7.2 (`sqlalchemy.text()`) is deferred to P2 — no database code exists yet |
| P1.8 | `capability-protocols` | phase | **archived** (2026-04-20) | — | new (harness architecture redesign) | Five capability protocols (GuardrailProvider, SandboxProvider, MemoryPolicy, ToolPolicy, ContextProvider) + CapabilityResolver + two-tier harness split (SDK vs Host) + ClaudeCodeHarness + CLI export subcommand + delegation guardrail integration |
| P2 | `memory-architecture` | phase | **archived** (2026-04-21) | §1.2, §8.1 | perplexity §8.1 + old P3 | `core/memory.py` MemoryManager + `core/graphiti.py` Graphiti/FalkorDB client factory + per-persona AsyncEngine + `memory`/`preferences`/`interactions` tables + CLI `db upgrade/downgrade` + `export-memory` subcommands. Implements `MemoryPolicy` protocol from P1.8. `PostgresGraphitiMemoryPolicy` auto-selected when `database_url` configured |
| P3 | `http-tools-layer` | phase | **archived** (2026-04-24) | §8.2 | perplexity §8.2 + old P2 | `src/assistant/http_tools/` — `/openapi.json`-based discovery with `$ref` resolution (D10), `_build_tool()` Pydantic-model + async-callable generator, auth header handling (D11 structured + legacy compat), registry, `--list-tools` CLI flag, integration tests against mock server under D9 security posture (streaming 10 MiB cap, no redirects, credential redaction) |
| P4 | `observability` | phase | **archived** (2026-05-03) | §1.1, §8.3 | perplexity §8.3 (new) | `core/observability.py` — `@traced` decorator, spans on `HarnessAdapter.invoke()` and `DelegationSpawner.delegate()`, token + latency + cost tracking per persona/role. Langfuse backend default; OpenLLMetry adapter optional |
| P5 | `ms-graph-extension` | phase | **archived** (2026-05-09) | §8.4 | perplexity §8.4 + old P5 | Real `ms_graph`, `teams`, `sharepoint`, `outlook` extensions (replaces P1 stubs). MSAL auth, httpx client, OAuth refresh. Full MS Agent Framework harness implementation replacing P1's `NotImplementedError` stub |
| P5.5 | `binding-manifest` | phase | pending | — | new (SPI framing follow-up, docs/architecture/) | Declarative `binding.yaml` per persona naming providers per primitive slot (model, harnesses, memory, identity, capability_registry, observability, sandbox); `BindingValidator` at startup with loud failures and compatibility-group enforcement; **BREAKING** `MemoryManager` cleanup (drop `persona: str` param — invariant per process under git-as-multi-tenancy); CLI `assistant binding {check,show,explain}`. Foundational for P5.6 / P5.7 / P14.5 / P15 / P18. Proposal lives at `openspec/changes/binding-manifest/`. |
| P5.6 | `capability-registry` | phase | pending | — | new (SPI framing follow-up) | Unifying primitive over `HttpToolRegistry` + extension tools + MCP servers with multiple consumer projections (LangChain, MSAF, Pi, MCP, CLI). OpenAPI canonical form + AA extensions (streaming, scoping, per-projection auth). Replaces `Extension` dual-surface methods (`as_langchain_tools()` / `as_ms_agent_tools()`) with `register(registry)` per documented leak in `docs/architecture/interface-stability.md`. Depends on P5.5 binding-manifest (registry provider declared in binding). |
| P5.7 | `conformance-test-harness` | phase | pending | — | new (SPI framing follow-up) | `tests/conformance/` infrastructure with shared fixtures; defines local-vs-managed conformance tier split per `docs/architecture/interface-stability.md`; gates stability promotion from Experimental → Provisional. Prerequisite for any new provider phase (P5.8 pi-harness, P14 google-extensions). |
| P5.8 | `pi-harness` | phase | pending | — | new (SPI framing follow-up) | Adds Pi (https://pi.dev/, github.com/earendil-works/pi) as a third harness adapter via `pi --mode rpc` subprocess + LF-delimited JSONL bridge. Validates `capability-registry` end-to-end with a non-Python harness consumer; proves the SPI claim by adding a non-Python harness without per-extension changes. Depends on P5.6 capability-registry (for MCP projection of tools); conformance via P5.7. |
| P5.9 | `interface-stability-ci-gate` | non-phase (tooling) | pending | — | new (ledger discipline) | CI check that fails when files under `src/assistant/{harnesses,extensions,core/memory,telemetry}/` are modified without a corresponding `docs/architecture/interface-stability.md` touch. Implements the "ledger drift mitigation" discipline from the architecture docs. Can land any time after P5.7. |
| P6 | `a2a-server` | phase | pending | §6, §8.5 | perplexity §8.5 (new; was Phase-16 "out of scope") | `src/assistant/a2a/` — server.py, task_handler.py, agent_card.py. Exposes `/a2a/v1/message:stream` endpoint. Serves `.well-known/agent.json`. Lets Copilot Studio Chief of Staff delegate to this assistant. **Scope expansion per SPI framing analysis**: also the inter-persona bridge for cross-deployment delegation within the user's own ecosystem (personal-process ↔ work-process); includes client side (this assistant delegating to remote A2A endpoints, including its own other-persona deployments). |
| P7 | `scheduler` | phase | pending | §2.1, §8.6 | perplexity §8.6 (new) | `core/scheduler.py` — cron (croniter) + calendar-event + polling triggers. `schedules:` section in `persona.yaml`. `--daemon` CLI flag. Morning briefing / email triage / pre-meeting brief hooks |
| P8 | `obsidian-vault` | phase | pending | §2.2, §8.7 | perplexity §8.7 (new) | Bi-directional Obsidian vault sync, split by authoring domain. Vault config declares `notes_dir` (human-authored: frameworks, meeting notes, raw thoughts — synced **into** ACA as indexed source) and `agent_dir` (agent-authored: entity hub pages, compiled summaries — rendered **from** ACA; frontmatter declares `agent_maintained: true`, `compiled_from: <entity_id>`, `regenerated_at: <ts>`; hand-edits may be overwritten on regeneration). Preferred: two endpoints on `agentic-content-analyzer` (`/index/vault-notes` for inbound, `/render/agent-folder` for outbound) invoked by a persona extension. Fallback: standalone `extensions/obsidian.py` with wikilink parsing + pgvector index covers the `notes_dir → ACA` direction only; `agent_dir` rendering deferred until ACA endpoint exists. Headless personas (no vault) skip both directions without penalty. Doctrine/frameworks remain in the persona submodule (loaded via P1.8 `ContextProvider`) — explicitly **not** vault content. |
| P9 | `error-resilience` | phase | **archived** (2026-05-04) | §1.3, §8.8 | perplexity §8.8 (new) | `core/resilience.py` — `tenacity`-based retry on transient HTTP failures, circuit breaker per backend, graceful degradation (agent notes unavailability instead of silent omission). Applied to http_tools client + extension `health_check()` |
| P10 | `extension-lifecycle` | phase | pending | §3.1, §8.9 | perplexity §8.9 (new) | Extend `Extension` protocol with `initialize()`, `shutdown()`, `refresh_credentials()` lifecycle hooks. `PersonaRegistry.load_extensions()` calls `initialize()` post-load; registers shutdown handler |
| P11 | `harness-routing` | phase | pending | §3.2, §8.10 | perplexity §8.10 (new) | Dynamic harness selection in `harnesses/factory.py`. `--harness auto` default. Routes M365-tool tasks → MS Agent Framework, complex reasoning → Deep Agents. **Framing per SPI analysis**: routing is *intra-persona* — selection is among the harnesses the persona's binding manifest (P5.5) declares. Binding validator gates which harnesses are eligible |
| P12 | `delegation-context` | phase | pending | §3.3, §5 P1, §8.11 | perplexity §8.11 + old P8 + §5 P1 router | `DelegationContext` dataclass (parent_role, delegation_chain, memory_snippets, conversation_summary, constraints). Cycle detection. `delegate_parallel`. Monitoring/cancellation. Delegation analytics tables. **Includes `delegation/router.py` intent-classification logic** for automatic delegation routing (perplexity §5 P1 item; was missing from v2 scope). **Framing per SPI analysis**: explicitly *same-persona, same-process*. Cross-persona delegation is P6 A2A, not delegation-context |
| P13 | `security-hardening` | phase | pending | §4, §8.12 | perplexity §8.12 (new) | Extension `manifest.yaml` with SHA-256 hashes verified before `spec.loader.exec_module()` (single-persona concern: preventing malicious extension code in your own process). **Scope reduction per SPI analysis**: the original "per-persona env var scoping in `_env()`" and "per-persona `.env` files" items are dropped — they solved a multi-tenant problem that doesn't exist under git-as-multi-tenancy. Each persona deployment is its own process and inherits its own env directly |
| P14 | `google-extensions` | phase | pending | — | original P4 | Real `gmail`, `gcal`, `gdrive` extension implementations. OAuth refresh via the P10 lifecycle hooks. **Dependency added per SPI analysis**: conformance via P5.7 conformance-test-harness |
| P14.5 | `persona-deployment-kit` | phase | pending | — | new (SPI framing follow-up) | Reusable scaffolding for new persona deployments: DB provisioning script, vault provisioning, submodule template (extends existing `scripts/init-persona-repo.sh`), `binding.yaml` scaffold, secrets bootstrap, observability sink config, satisfiability health check (runs `assistant binding check`). Depends on P5.5 binding-manifest. Makes P15 a thin "use the kit" PR rather than carrying all the deployment R&D itself |
| P15 | `work-persona-deployment` (formerly `work-persona-config`) | phase | pending | — | original P6 (renamed per SPI framing) | Stand up the work persona deployment: create `assistant-config-work` submodule, wire into `.gitmodules`, populate work persona config + role overrides + `binding.yaml`. Uses P14.5 deployment kit. Deferred until work machine available. Per SPI analysis: framed as a *deployment event* (new bound process), not "configure multi-tenancy" |
| P16 | `cli-harness-integrations` | phase | pending | — | original P7 | Deeper Claude Code / Codex / Gemini integrations — slash commands in `.claude/commands/`, `.codex/skills/`, `.gemini/settings.json`. **Framing per SPI analysis**: each CLI integration is a projection of the persona's binding into another runtime's discovery format; the `HostHarnessAdapter` (P1.8) is the right home; persona-aware routing is per-binding-manifest |
| P17 | `mcp-server-exposure` | phase | pending | — | original P9 | Expose the assistant as an MCP server so other Claude Code sessions can invoke it as a tool. Complementary to P6 A2A (different protocols, different clients). **Dependency added per SPI analysis**: benefits from P5.6 capability-registry's MCP projection layer |
| P18 | `persona-deployment-runtime` (formerly `railway-deployment`) | phase | pending | — | original P10 (renamed per SPI framing) | Operational expression of git-as-multi-tenancy: run each persona instance as its own deployment (Railway service or equivalent), with deployment manifests, secrets management, observability sink wiring, A2A endpoint exposure. Renamed from `railway-deployment` because the substance is "each persona = one deployment unit," not Railway-specific. Depends on P14.5 (kit) + P15 (first deployment user) + P16 |
| X1 | `add-teacher-role` | non-phase (feature) | archived 2026-05-15 | — | user-requested (2026-04-16) | Add `teacher` role with Feynman + Socratic skill files; `--method` CLI flag and `/method` / `/methods` REPL commands; declare `content_analyzer:*` preferred tools that bind via the archived P3 http-tools layer once ACA aligns its operationIds. Independent of the P-phase DAG. Followups: ACA#421 (operationIds), assistant#31 (observability), #32 (role-params abstraction when N≥2 roles), #33 (persona-scoped LLM auth). |

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
 ├─→ P1.7 bootstrap-fixes (archived; all §7 items resolved or folded into P2)
 │
 ├─→ P1.8 capability-protocols (archived; harness architecture redesign)
 │    ├─→ P2 memory-architecture             (implements MemoryPolicy protocol;
 │    │                                       §7.2 sqlalchemy.text() folded into P2 scope)
 │    ├─→ P3 http-tools-layer                (implements ToolPolicy source)
 │    ├─→ P11 harness-routing                (three-tier routing uses CapabilityResolver)
 │    ├─→ P13 security-hardening             (implements GuardrailProvider;
 │    │                                       also needs P10 lifecycle hooks)
 │    └─→ P16 cli-harness-integrations       (extends HostHarnessAdapter exports)
 │
 ├─→ P4 observability                        (independent of P1.7/P1.8; lands early for tracing)
 ├─→ P10 extension-lifecycle                 (independent of P1.7/P1.8; initialize/shutdown hooks)
 │
 ├─→ P2 memory-architecture (archived) ──┬─→ P7 scheduler         (needs memory for briefings)
 │                            ├─→ P8 obsidian-vault    (needs memory for indexing backend)
 │                            └─→ P12 delegation-context  (needs memory for context snippets;
 │                                                        scope includes delegation/router.py
 │                                                        intent classification per §5 P1)
 │
 ├─→ P3 http-tools-layer ─────┬─→ P5 ms-graph-extension ──┬─→ P6 a2a-server           (exposes assistant via A2A)
 │                            │                          └─→ P14 google-extensions    (gmail/gcal/gdrive)
 │                            └─→ P9 error-resilience     (retries applied to http_tools client)
 │
 ├─→ P10 extension-lifecycle ─→ P13 security-hardening  (manifest validation uses lifecycle hook;
 │                                                       env-scoping scope reduced per SPI analysis)
 └─→ P5 ms-graph-extension    ─→ P11 harness-routing    (routes M365 tasks once MS Agent Framework is real;
                                                         intra-persona only — binding manifest declares
                                                         eligible harnesses)

# SPI framing follow-up phases (new per docs/architecture/)
P2 + P3 + P5 (archived)
 └─→ P5.5 binding-manifest  (declarative deployment artifact + validator;
     │                       breaks MemoryManager persona-param leak)
     ├─→ P5.6 capability-registry   (unifies HttpToolRegistry + extensions + MCP;
     │                               replaces Extension dual-surface)
     │    ├─→ P5.8 pi-harness        (consumes MCP projection)
     │    └─→ P17 mcp-server-exposure (benefits from MCP projection layer)
     ├─→ P5.7 conformance-test-harness  (gates Experimental→Provisional promotion;
     │    │                              required-before for new providers)
     │    ├─→ P5.8 pi-harness          (conformance against capability-registry contract)
     │    └─→ P14 google-extensions    (conformance against MemoryManager / Extension)
     ├─→ P5.9 interface-stability-ci-gate  (small tooling; CI check on ledger drift)
     ├─→ P14.5 persona-deployment-kit  (scaffolding; depends on binding manifest schema)
     │    └─→ P15 work-persona-deployment  (first kit consumer)
     │         └─→ P18 persona-deployment-runtime  (operationalizes per-persona deploy)
     └─→ P11 harness-routing  (binding validator gates eligible harnesses)

# Independent / long-range
P15 work-persona-deployment   needs P5 + P8 + P14.5 (deployment kit); also triggered by machine availability
P17 mcp-server-exposure       needs P6 (protocol parallel; A2A and MCP expose the same assistant);
                              additionally benefits from P5.6 capability-registry's MCP projection
P18 persona-deployment-runtime needs P14.5, P15, P16
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
| **Memory hierarchy** (memory.md derived from Postgres+Graphiti — perplexity §1.2) | P2 establishes; P5.5 cleans up persona-param leak; P7/P8/P12 consume |
| **Observability** (tracing, cost per persona×role — §1.1) | P4 establishes; all later phases add spans to their new code paths |
| **Resilience** (retry, circuit breaker — §1.3) | P9 establishes; P3/P5/P14/P17 adopt |
| **Security boundaries** (credential scoping, manifest validation — §4) | P13 establishes (scope reduced per SPI analysis); all phases loading config must comply |
| **Proactive execution** (scheduler + A2A + Obsidian RAG — §2) | P6/P7/P8 — the differentiated Chief-of-Staff story |
| **SPI / binding architecture** (git-as-multi-tenancy → primitives as interfaces, providers selected per deployment via binding manifest — see `docs/architecture/`) | P5.5 binding-manifest establishes; P5.6 capability-registry, P5.7 conformance-test-harness, P5.8 pi-harness, P5.9 ci-gate, P14.5 deployment-kit consume; P15/P18 are deployment-event applications of the framework |
| **Per-deployment topology** (each persona = one deployment unit; git access control + filesystem + process boundaries enforce isolation, not application code) | P5.5 makes deployment declarative; P14.5 makes deployment reproducible; P15 is the first second-persona deployment; P18 operationalizes per-persona services |

## Out of scope for roadmap v2

Items from bootstrap spec Phase 16 not adopted by perplexity §8.
Amended per SPI framing analysis (see `docs/architecture/`):

- **Cross-persona bridge** — no longer out of scope; reframed under
  P6 a2a-server (scope expanded to include inter-persona delegation
  between the user's own deployments).
- **Persona config encryption** — explicit non-goal (not a deferral).
  Git access control on private persona submodules is the chosen
  encryption mechanism; per-persona deployment topology is the
  chosen isolation mechanism. Adding application-layer encryption
  would duplicate what git + filesystem + process boundaries
  already provide under git-as-multi-tenancy.
- **Multi-model routing** (beyond the harness-routing in P11) —
  remains deferred; revisit when a persona's binding manifest
  declares multiple model providers.
- **Role learning** — remains deferred.
- **NotebookLM integration** — remains deferred.

Each remaining deferred item may re-enter a future v3 roadmap if
perplexity-equivalent review surfaces demand.
