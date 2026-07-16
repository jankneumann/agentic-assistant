# agentic-assistant — OpenSpec Roadmap v3

> **Supersedes** roadmap v2 (`roadmap-v2-perplexity-integration`, reconciled
> by `roadmap-v2-reconciliation`). v3 integrates the 2026-07-07 architecture
> review (`docs/architecture-analysis/2026-07-07-architecture-review.md`),
> which re-targets the project at a **heterogeneous fleet**: ASUS Ascent
> GX10 (local inference / always-on node), PowerSpec G762 (workstation),
> Claude/Gemini/Codex subscription seats (host-harness tier), OpenRouter +
> hyperscaler model gardens (metered SDK tier), and optional meta-harness
> control planes (Omnigent, NemoClaw). The v2 roadmap is preserved in git
> history. Amended 2026-07-16 with the owner's ecosystem brief
> (`docs/architecture-analysis/2026-07-16-ecosystem-pillars.md`): six
> pillars — model routing, memory + continual learning, orchestration +
> agent IAM + clean-room sharing, sandboxing, eval/simulation feedback
> loop, multimodal I/O — adding rows P24–P29.
>
> Change that introduced this rewrite: `roadmap-v3-heterogeneous-fleet`.

## Guiding principles

1. **One OpenSpec proposal per phase** — fine-grained, independently
   reviewable, each eligible for `/plan-feature` → `/autopilot`.
2. **The Dependency graph represents real functional prerequisites** —
   phases shown as siblings have no functional coupling and MAY run in
   any order. The "Recommended execution order" section is advisory.
3. **Change-ids are the identity; `#` labels are ordering hints only.**
   v3 keeps all v2 numbers for unchanged scope and appends P19+ / X3+
   for new scope. (`P14a` exists because `harness-ag-ui-bridge` was
   labeled "P14" in its archive commit while the v2 table already used
   P14 for `google-extensions` — v3 records both without renumbering.)
4. **Docs — not CI — enforce the DAG.** Consult this file before invoking
   `/plan-feature` or `/autopilot` for any phase.
5. **One model seam, not two.** The seam is the `ModelProvider`
   protocol (P24/P19): a harness-neutral `ModelRef` (wire dialect,
   endpoint, credential ref, capability tags, pricing) resolved by the
   router, with thin per-harness **bindings** — LangChain
   `init_chat_model` for LangChain-native harnesses, `agent-framework`
   chat clients for MSAF, a raw OpenAI-compatible client for direct
   calls (embeddings, summarization). No second provider-abstraction
   library (e.g., LiteLLM) unless a binding proves insufficient —
   recorded as an ADR when P19 lands.
6. **Stay the persona/role/capability layer.** Meta-harnesses (Omnigent,
   NemoClaw) are control planes *above* this repo; we integrate under
   them (P22) rather than rebuilding session-sharing, sandbox fleets, or
   governance planes in-repo.
7. **Standards-first seams.** Every component boundary adopts an existing
   protocol where one has converged — OpenAPI (service→tool), MCP
   (tool protocol), A2A (agent↔agent), AG-UI + MCP-UI (agent↔user),
   OpenAI-compatible / Anthropic / Gemini wire APIs (model calling),
   OTel GenAI semconv (observability), Agent Skills (skill packaging),
   OAuth 2.1 + MCP auth (surface auth). Where no standard has converged
   (model capability/pricing metadata, memory, sandbox config, agent
   identity, evals) our own protocols are **placeholders shaped for
   migration** — see the matrix in
   `docs/architecture-analysis/2026-07-16-protocol-standards.md`.

## Proposal sequence

| # | Change ID | Kind | Status | Perplexity § | Source | Description |
|---|-----------|------|--------|--------------|--------|-------------|
| P1 | `bootstrap-vertical-slice` | phase | **archived** (2026-04-12) | — | original P1 | Core library + Deep Agents harness + CLI + 5 roles + personal persona + delegation + tests + CI |
| P1.5 | `test-privacy-boundary` | phase | **archived** (2026-04-13) | — | new (IR hygiene from P1 validation) | Separate public tests from private persona data: two-layer (collection-time substring scan + runtime FS patching) boundary guard, `ASSISTANT_PERSONAS_DIR` env-var contract, `scripts/push-with-submodule.sh` atomic dual-commit push wrapper |
| P1.6 | `sync-test-privacy-boundary-spec` | non-phase (spec-sync) | **archived** (2026-04-13) | — | spec-sync follow-up of P1.5 | Listed for chronological context. Spec-only change that codified five drift items found during P1.5 validation (env-var contract, subprocess `executable=`/`cwd=` kwarg coverage, hygiene-test exclusion list, submodule `parents[N]` abstraction, atomic-push wrapper requirement) |
| P1.7 | `bootstrap-fixes` | phase | **archived** (2026-04-20) | §7.1–§7.5 | perplexity §7 | All items resolved: §7.1 CLI `-H` fix landed in P1; §7.3 `deepagents` v0.5.2 confirmed valid; §7.4 entry point landed in P1; §7.5 `src_name` fix landed in P1. §7.2 (`sqlalchemy.text()`) was deferred to P2 |
| P1.8 | `capability-protocols` | phase | **archived** (2026-04-20) | — | new (harness architecture redesign) | Five capability protocols (GuardrailProvider, SandboxProvider, MemoryPolicy, ToolPolicy, ContextProvider) + CapabilityResolver + two-tier harness split (SDK vs Host) + ClaudeCodeHarness + CLI export subcommand + delegation guardrail integration |
| P2 | `memory-architecture` | phase | **archived** (2026-04-21) | §1.2, §8.1 | perplexity §8.1 + old P3 | `core/memory.py` MemoryManager + `core/graphiti.py` Graphiti/FalkorDB client factory + per-persona AsyncEngine + `memory`/`preferences`/`interactions` tables + CLI `db upgrade/downgrade` + `export-memory` subcommands. Implements `MemoryPolicy` protocol from P1.8. `PostgresGraphitiMemoryPolicy` auto-selected when `database_url` configured |
| P3 | `http-tools-layer` | phase | **archived** (2026-04-24) | §8.2 | perplexity §8.2 + old P2 | `src/assistant/http_tools/` — `/openapi.json`-based discovery with `$ref` resolution (D10), `_build_tool()` Pydantic-model + async-callable generator, auth header handling (D11 structured + legacy compat), registry, `--list-tools` CLI flag, integration tests against mock server under D9 security posture (streaming 10 MiB cap, no redirects, credential redaction) |
| P4 | `observability` | phase | **archived** (2026-05-03) | §1.1, §8.3 | perplexity §8.3 (new) | `core/observability.py` — `@traced` decorator, spans on `HarnessAdapter.invoke()` and `DelegationSpawner.delegate()`, token + latency + cost tracking per persona/role. Langfuse backend default; OpenLLMetry adapter optional |
| P5 | `ms-graph-extension` | phase | **archived** (2026-05-09) | §8.4 | perplexity §8.4 + old P5 | Real `ms_graph`, `teams`, `sharepoint`, `outlook` extensions (replaces P1 stubs). MSAL auth, httpx client, OAuth refresh. Full MS Agent Framework harness implementation replacing P1's `NotImplementedError` stub |
| P6 | `a2a-server` | phase | pending | §6, §8.5 | perplexity §8.5 (new; was Phase-16 "out of scope") | `src/assistant/a2a/` — server.py, task_handler.py, agent_card.py. Exposes `/a2a/v1/message:stream` endpoint. Serves `.well-known/agent.json`. Lets external orchestrators (Copilot Studio, meta-harnesses) delegate to this assistant. Also a prerequisite surface for P22 meta-harness composition |
| P7 | `scheduler` | phase | pending | §2.1, §8.6 | perplexity §8.6 (new) | `core/scheduler.py` — cron (croniter) + calendar-event + polling triggers. `schedules:` section in `persona.yaml`. `--daemon` CLI flag. Morning briefing / email triage / pre-meeting brief hooks. Scheduled work SHOULD default to the local/cheap routing tiers from P19/P20 |
| P8 | `obsidian-vault` | phase | pending | §2.2, §8.7 | perplexity §8.7 (new) | Bi-directional Obsidian vault sync, split by authoring domain. Vault config declares `notes_dir` (human-authored — synced **into** ACA as indexed source) and `agent_dir` (agent-authored — rendered **from** ACA; frontmatter declares `agent_maintained: true`, `compiled_from: <entity_id>`, `regenerated_at: <ts>`). Preferred: two endpoints on `agentic-content-analyzer` invoked by a persona extension. Fallback: standalone `extensions/obsidian.py` covering `notes_dir → ACA` only. Headless personas skip both directions. Doctrine/frameworks remain in the persona submodule (loaded via P1.8 `ContextProvider`) |
| P9 | `error-resilience` | phase | **archived** (2026-05-04) | §1.3, §8.8 | perplexity §8.8 (new) | `core/resilience.py` — `tenacity`-based retry on transient HTTP failures, circuit breaker per backend, graceful degradation. Applied to http_tools client + extension `health_check()` |
| P10 | `extension-lifecycle` | phase | pending | §3.1, §8.9 | perplexity §8.9 (new) | Extend `Extension` protocol with `initialize()`, `shutdown()`, `refresh_credentials()` lifecycle hooks. `PersonaRegistry.load_extensions()` calls `initialize()` post-load; registers shutdown handler |
| P11 | `harness-routing` | phase | pending | §3.2, §8.10 | perplexity §8.10, reframed by arch-review G-C | Dynamic **harness** selection in `harnesses/factory.py` (`--harness auto`). Routes M365-tool tasks → MS Agent Framework, complex reasoning → Deep Agents, interactive/coding tasks → host-harness (subscription) tier. Consumes the capability vocabulary and routing engine from P19 — **model** routing lives in P19, harness routing here |
| P12 | `delegation-context` | phase | pending | §3.3, §5 P1, §8.11 | perplexity §8.11 + old P8 + §5 P1 router | `DelegationContext` dataclass (parent_role, delegation_chain, memory_snippets, conversation_summary, constraints). Cycle detection. `delegate_parallel`. Monitoring/cancellation. Delegation analytics tables. Includes `delegation/router.py` intent-classification logic |
| P13 | `security-hardening` | phase | pending | §4, §8.12 | perplexity §8.12 (new) | Per-persona env var scoping in `_env()` helper (behind the P24 `CredentialProvider` seam; OpenBao becomes the production backend when P25 lands). Per-persona `.env` files. Extension `manifest.yaml` with SHA-256 hashes verified before `spec.loader.exec_module()`. First non-allow-all `GuardrailProvider` (budget + action policies shared with P19 routing) |
| P14 | `google-extensions` | phase | pending | — | original P4 | Real `gmail`, `gcal`, `gdrive` extension implementations. OAuth refresh via the P10 lifecycle hooks |
| P14a | `harness-ag-ui-bridge` | phase | **archived** (2026-05-21) | — | new (openspec/explore/generative-ui-layer.md) | AG-UI SSE transport: `transports/ag_ui/` event mapper (9 AG-UI v1 event types, D8 two-phase error contract), `web/` FastAPI app factory + `POST /chat` SSE + `GET /health`, `assistant serve` CLI subcommand. Added `ag-ui-emitter` + `web-server` capability specs. *Row added retroactively by v3 — the change was archived without a v2 row; its archive commit label "P14" collided with `google-extensions` above* |
| P15 | `work-persona-config` | phase | pending | — | original P6 | Create `assistant-config-work` submodule, wire into `.gitmodules`, populate work persona config + role overrides. Deferred until work machine available |
| P16 | `cli-harness-integrations` | phase | pending | — | original P7 + arch-review G-C/H4 | Subscription-tier completion: register the `codex` host harness (currently in the persona template but **not** in `harnesses/factory.py`), add a `gemini_cli` host harness, deeper Claude Code / Codex / Gemini integrations (slash commands in `.claude/commands/`, `.codex/skills/`, `.gemini/`), persona-aware routing, template↔registry consistency test |
| P17 | `mcp-server-exposure` | phase | pending | — | original P9 | Expose the assistant as an MCP server so other sessions/harnesses can invoke it as a tool. Complementary to P6 A2A (different protocols, different clients); together they form the composition surface consumed by P22 |
| P19 | `model-provider-routing` | phase | pending | — | new (arch-review G-A) | Provider-agnostic model layer + **capability-based model routing**. Persona-level `models:` registry — named entries with provider string (`anthropic:`, `openai:`, `google_genai:`, `google_vertexai:`, `bedrock_converse:`, `ollama:`, OpenRouter via OpenAI-compatible `base_url`), capability tags (`fast`, `cheap`, `long-context`, `coding`, `vision`, `local-only`, `private-data-ok`), and ordered fallback chains. `core/model_router.py` resolves (capability requirements → harness-neutral `ModelRef`); per-harness bindings adapt the `ModelRef` (LangChain `init_chat_model` for DeepAgents, `agent-framework` chat clients for MSAF, raw OpenAI-compatible client for direct calls such as embeddings/summarization); per-persona API-key resolution via the `CredentialProvider` seam (P24 contract 7; env-var impl at first, OpenBao backend when P25 lands); budget enforcement via `GuardrailProvider`; cost attribution through existing telemetry spans. Both SDK harnesses consume the router instead of raw model-id strings. Catalog format mirrors the OpenRouter `/models` schema (pricing, context length, modalities) so cloud entries sync verbatim and local entries are hand-authored in the same shape. Reuse posture: shares the catalog schema + pricing data with `agentic-coding-tools`' cost-aware routing (contracts, not code — protocol-standards doc Part C); the router implementation is assistant-specific |
| P20 | `local-inference-node` | phase | pending | — | new (arch-review G-B) | GX10 (or any OpenAI-compatible local endpoint: NIM / vLLM / Ollama) as first-class model-registry entries. Local embedding model wiring for Graphiti/memory search. Routing policy: `private-data-ok`-tagged operations (memory summarization, embeddings, interaction logging) resolve local-first; scheduled/background work prefers local/cheap tiers. Health-checked endpoints with cloud fallback via P19 fallback chains |
| P21 | `memory-retrieval-activation` | phase | in-progress | §1.2 (completion) | new (arch-review G-E; promoted from the "P5b candidate" note in CLAUDE.md) | Make memory *felt*: implement real `MemoryPolicy.get_recent_snippets()` against `MemoryManager` (all four policies currently return `[]`), wire `MemoryManager` retrieval into the DeepAgents context path (today it uses only `InMemorySaver` + file memory), post-turn interaction/episode capture, and MSAF `## Recent context` fed with live snippets. Retrieval + summarization SHOULD be routable to local models once P20 lands |
| P22 | `meta-harness-compat` | phase | pending | — | new (arch-review G-D) | Composition **under** external meta-harnesses rather than rebuilding one. Deliverables: Omnigent-composable agent definition (agent YAML + common API surface over the existing AG-UI/A2A/MCP endpoints), evaluation of NemoClaw/OpenShell as the sandboxed always-on runtime for the GX10 deployment, and the first real `SandboxProvider` implementation (container/OpenShell-backed) replacing `PassthroughSandbox`. Outcome is an ADR: adopt / integrate / defer per meta-harness |
| P23 | `deployment-topology` | phase | pending | — | new (arch-review G-F); absorbs old P18 `railway-deployment` (original P10) | Home-lab deployment: GX10 as always-on node (assistant daemon, per-persona Postgres/ParadeDB + FalkorDB, local inference from P20), G762 as interactive workstation, LAN exposure of AG-UI/A2A/MCP surfaces, service definitions (systemd or compose), per-persona secrets handling, DB backup/restore runbook. Railway (the entire scope of former P18) demoted to an optional cloud-variant appendix of this phase |
| P24 | `capability-protocols-v2` | phase | in-progress | — | new (arch-review §"seams"; ecosystem pillars 1+4) | **Contracts-only pre-phase** (spec deltas, no implementations) codifying five seams before parallel execution: (1) `ModelProvider` as capability slot #6 in `CapabilitySet` (chat + embeddings, capability tags, cost catalog, `GuardrailProvider` budget hook via `ActionRequest(action_type="model_call")`), resolving to a harness-neutral `ModelRef` with thin per-harness bindings (LangChain `init_chat_model`, MSAF chat clients, raw OpenAI-compatible for direct calls); (2) harness-neutral MCP-shaped `ToolSpec` + per-harness adapters, deprecating per-harness `as_*_tools()` extension methods; (3) `SandboxConfig` v2 with three planes — filesystem (mounts), network (deny-by-default egress), credentials (secret visibility) — and a named enforcement seam at tool invocation; (4) `create_agent(tools)` signature cleanup (ToolPolicy is the sole tool aggregator, designed so a tool-search/ranking stage can slot in); (5) durable-session contract — adopt LangGraph checkpointer interface (Postgres impl) for the DeepAgents harness + a session registry (create/lookup/expire by `thread_id`; `web/app.py` currently builds one global harness at startup) so P7 daemon / P6 A2A can multiplex; (6) **approval interrupt/resume**: consume `ActionDecision.require_confirmation` (defined at `capabilities/types.py:42`, consumed by nothing) — guardrail block → checkpointed suspend → approval request → audited resume, with Codex-style escalation-with-justification. The approval protocol is **channel-agnostic**: one `ApprovalRequest` shape mirroring MCP elicitation, rendered by AG-UI first, then email (Outlook/Gmail extensions; decision via reply or signed link — suspend survives hours-long round-trips) and messaging channels (P29 Channel binding); represented as MCP elicitation / A2A `input-required` on served surfaces; (7) `CredentialProvider` seam — one lookup interface for secrets/API keys with the existing `_env()` indirection as default impl, so P25 can swap in the OpenBao backend without touching call sites. Standards mapping per `docs/architecture-analysis/2026-07-16-protocol-standards.md` |
| P25 | `agent-iam` | phase | pending | — | new (ecosystem pillar 3) | Agent identity & access management: `AgentIdentity` principal (persona, role, delegation chain, session) attached to every `ActionRequest`, delegation hop, and inbound/outbound A2A/MCP call; agent-card authn on server surfaces; scoped short-lived per-persona credentials on client side. Explicitly models **inbound** (who may call us — OAuth 2.1 / MCP auth spec / A2A card schemes) vs **outbound** (what we present on the user's behalf — token vault replacing ambient env vars) per the AgentCore Identity lesson. Vault backend is **OpenBao** (already operated as a service for the coding coordinator; reuse policy — share stateful services): per-persona policies/mounts, short-lived dynamic credentials, AppRole/JWT auth per agent principal, audit log — implementing the P24 `CredentialProvider` seam (env-var impl remains the standalone/dev fallback so a fresh clone boots without a vault). Extends P13 env scoping; makes P12's `delegation_chain` attributable |
| P26 | `knowledge-clean-room` | phase | pending | — | new (ecosystem pillar 3); re-scopes the deferred "cross-persona bridge" | Declassification gateway for clean-room knowledge sharing: policy-driven, audited flow `source persona memory → sanitization (reuse telemetry/sanitize.py) → shared knowledge space → consuming persona/external agent`, with per-fact provenance and revocation. Runtime analogue of the test-time privacy boundary |
| P27 | `eval-simulation-loop` | phase | pending | — | new (ecosystem pillar 5) | Close the feedback loop: **simulation personas** (`tool_sources` pointing at simulator endpoints promoted from `tests/mocks/` + `tests/fixtures/graph_responses/`; `assistant simulate` surface); per-role gen-eval scenario suites (CI + scheduled) building on `evaluation/`; Langfuse trace→eval-dataset export so production regressions become permanent tests; eval gate consumed by P28 and by prompt/routing config changes. Self-improvement is propose → eval → human-approved diff, never self-merge |
| P28 | `continual-learning` | phase | pending | — | new (ecosystem pillar 2); re-scopes the deferred "role learning" | Memory that grows, with a **source-agnostic feedback abstraction**: a `FeedbackEvent` → `ImprovementProposal` pipeline whose sources are both human (thumbs/corrections via the P24 approval/feedback channels — AG-UI, email, messaging) and machine (P27 eval results, guardrail denials, resilience/circuit-breaker stats, telemetry cost anomalies, self-critique passes). Scheduled reflection/consolidation jobs (Graphiti episodes → semantic facts → regenerated `memory.md` prompt layer); preference distillation into persona prompt layer; role-learning as prompt-layer suggestions. Proposals are risk-tiered (`RiskLevel`): low-risk classes MAY auto-apply by policy; higher tiers route through the P24 channel-agnostic approval gate. All applied changes are eval-gated (P27) and land as reviewable diffs in the persona submodule |
| P29 | `multimodal-io` | phase | pending | — | new (ecosystem pillar 6) + openspec/explore/generative-ui-layer.md | Multimodal in/out: typed image/audio/file parts in the `HarnessEvent` vocabulary + AG-UI mapping; voice via local ASR/TTS on the GX10 (P20 registry entries); document/image ingestion into memory/ACA indexing; generative-UI rendering (OpenUI Lang) as the data-facing modality. `Channel` adapters (email, messaging) double as approval/feedback transports for the P24 interrupt contract |
| X1 | `add-teacher-role` | non-phase (feature) | **archived** (2026-05-15) | — | user-requested (2026-04-16) | Add `teacher` role with Feynman + Socratic skill files; `--method` CLI flag and `/method` / `/methods` REPL commands; declare `content_analyzer:*` preferred tools binding via the P3 http-tools layer once ACA aligns its operationIds. Followups: ACA#421, assistant#31, #32, #33 |
| X2 | `fix-harness-conversation-memory` | non-phase (fix) | **archived** (2026-05-15) | — | bug fix (harness conversation continuity) | Listed for chronological context (row added retroactively by v3). Fixed cross-turn conversation memory in SDK harnesses |
| X3 | `repo-hygiene` | non-phase (maintenance) | **archived** (2026-07-16) | — | new (arch-review §4 H1–H5) | Backfill `## Purpose` in all 25 capability specs (all currently "TBD"); seed `docs/decisions/` with retroactive ADRs (SDK/Host split, capability protocols, AG-UI adoption, privacy boundary, model-seam choice, cross-repo reuse policy per protocol-standards doc Part C); fix `gen-eval` path dependency (`[tool.uv.sources]` breaks standalone clones on new machines) via publish/vendor/optional-group; pin `agent-framework-core` directly to dodge the namespace-package quirk. (`codex` registration moved to P16 where the harness work lives) |

## Status lifecycle

Each phase transitions: `pending` → `in-progress` (when `/plan-feature`
creates its proposal directory) → `archived` (when
`/openspec-archive-change` finalizes it). This table is the canonical
record — update it as part of the phase's final commit.

## Dependency graph

Edges represent **functional prerequisites** — phase B depends on a
concrete output of phase A — not chronological preference. Siblings MAY
run in any order.

```
P1 bootstrap-vertical-slice (archived)
 │
 ├─→ P1.5 test-privacy-boundary (archived) ─→ P1.6 (archived; spec-sync)
 ├─→ P1.7 bootstrap-fixes (archived)
 │
 ├─→ P1.8 capability-protocols (archived)
 │    ├─→ P2 memory-architecture (archived)
 │    ├─→ P3 http-tools-layer (archived)
 │    ├─→ P16 cli-harness-integrations    (extends HostHarnessAdapter exports)
 │    └─→ P24 capability-protocols-v2     (contracts-only: ModelProvider slot #6,
 │         │                              MCP-shaped ToolSpec, SandboxConfig
 │         │                              three planes, create_agent cleanup,
 │         │                              durable-session contract)
 │         ├─→ P13 security-hardening     (implements GuardrailProvider +
 │         │                              credential plane; also needs P10)
 │         ├─→ P19 model-provider-routing (implements ModelProvider slot;
 │         │    │                         budget via GuardrailProvider;
 │         │    │                         cost spans via P4 observability)
 │         │    ├─→ P11 harness-routing   (consumes P19 capability vocabulary;
 │         │    │                         M365 routing also needs P5 — archived)
 │         │    └─→ P20 local-inference-node (GX10 endpoints as registry entries;
 │         │                              local ASR/TTS tier feeds P29 voice)
 │         └─→ P22 meta-harness-compat    (implements the sandbox planes;
 │                                        composition surface via P14a + P6/P17)
 │
 ├─→ P4 observability (archived)
 ├─→ P10 extension-lifecycle              (independent; initialize/shutdown hooks)
 │
 ├─→ P2 memory-architecture (archived) ──┬─→ P7 scheduler                (needs memory for briefings)
 │                                       ├─→ P8 obsidian-vault           (needs memory for indexing)
 │                                       ├─→ P12 delegation-context      (needs memory snippets)
 │                                       └─→ P21 memory-retrieval-activation
 │                                            (snippets into harness context;
 │                                            local summarization once P20 lands)
 │
 ├─→ P3 http-tools-layer (archived) ─────┬─→ P5 ms-graph-extension (archived) ─┬─→ P6 a2a-server
 │                                       │                                    └─→ P14 google-extensions
 │                                       └─→ P9 error-resilience (archived)
 │
 ├─→ P10 extension-lifecycle ─→ P13 security-hardening   (manifest validation uses lifecycle hook)
 ├─→ P14a harness-ag-ui-bridge (archived) ─→ P22 meta-harness-compat
 │                                            (composition surface = AG-UI + A2A + MCP;
 │                                            also needs P6 and/or P17;
 │                                            SandboxProvider impl feeds back into P13 posture)
 └─→ P6 a2a-server ─→ P17 mcp-server-exposure   (protocol siblings; either unblocks P22)

# Independent / long-range
X3  repo-hygiene              no prerequisites; do first (unblocks clean clones on new machines)
P15 work-persona-config       needs P5 (archived); triggered by work-machine availability
P23 deployment-topology       needs P20 (local inference) + P7 (daemon mode);
                              Railway variant additionally needs P15, P16
P25 agent-iam                 needs P13 + an interop surface (P6 and/or P17)
P26 knowledge-clean-room      needs P25 (identities) + P21 (real retrieval)
P27 eval-simulation-loop      needs P4 (archived); scheduled runs benefit from P7
P28 continual-learning        needs P21 + P7 (reflection jobs) + P27 (eval gate)
P29 multimodal-io             needs P14a (archived); voice tier needs P20
```

## Recommended execution order (advisory)

Rationale in `docs/architecture-analysis/2026-07-07-architecture-review.md` §5.

1. **X3 `repo-hygiene`** — cheap; unblocks standalone clones (GX10 setup) and pays down doc debt.
2. **P24 `capability-protocols-v2`** — contracts before parallel execution: the stable interfaces `/autopilot-roadmap` work packages build against. Day-scale spec tasks, gates P13/P19/P22.
3. **P19 `model-provider-routing`** ∥ **P21 `memory-retrieval-activation`** — the two highest-leverage gaps: multi-provider access and memory that is actually used. Independent of each other.
4. **P27 `eval-simulation-loop`** — close the feedback loop early so every subsequent phase (and autopilot itself) is eval-gated; the mock/fixture assets and gen-eval adoption make this mostly integration work.
5. **P10 `extension-lifecycle`** → **P13 `security-hardening`** — lifecycle + first real guardrails (budgets shared with P19, credential plane from P24).
6. **P20 `local-inference-node`** — once the GX10 is racked; local/private routing tiers go live.
7. **P7 `scheduler`** — proactive value, now cheap to run on local tiers.
8. **P6 `a2a-server`** ∥ **P17 `mcp-server-exposure`** — the interop/composition surface.
9. **P11 `harness-routing`** — auto-selection across harness + subscription tiers.
10. **P22 `meta-harness-compat`** — compose under Omnigent; evaluate NemoClaw for the GX10 runtime; first real sandbox provider.
11. **P25 `agent-iam`** → **P26 `knowledge-clean-room`** — the trust layer, once interop surfaces and real retrieval exist.
12. **P8 `obsidian-vault`** ∥ **P12 `delegation-context`** — knowledge + delegation depth.
13. **P28 `continual-learning`** — reflection + preference distillation, eval-gated by P27.
14. **P29 `multimodal-io`** — voice/vision/generative UI; every earlier phase multiplies its value.
15. **P14 `google-extensions`**, **P15 `work-persona-config`**, **P16 `cli-harness-integrations`** — extension/persona breadth as machines and accounts allow.
16. **P23 `deployment-topology`** — solidify the fleet once its components exist.

## Phase-by-phase execution via autopilot

Per phase:

```bash
# 1. Plan
/plan-feature <change-id>   # e.g. model-provider-routing

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
| **Capability protocols** (guardrails, sandbox, memory policy, tool policy) | P1.8 establishes; P2 MemoryPolicy; P3 ToolPolicy; P13 GuardrailProvider; P22 SandboxProvider; P11/P16/P19 consume CapabilityResolver |
| **Model & compute tiers** (subscription seats / metered APIs / local inference — arch-review §1) | P19 establishes routing; P20 local tier; P11 harness tier; P16 subscription tier; P7 consumes cheap tiers; P13 enforces budgets |
| **Memory hierarchy** (Postgres + Graphiti; perplexity §1.2) | P2 establishes; P21 activates retrieval; P7/P8/P12 consume |
| **Observability** (tracing, cost per persona×role — §1.1) | P4 establishes; P19 attributes cost per model/tier; all later phases add spans |
| **Resilience** (retry, circuit breaker — §1.3) | P9 establishes; P3/P5/P14/P17/P20 adopt (P20: endpoint health + cloud fallback) |
| **Security boundaries** (credential scoping, manifest validation, sandboxing — §4) | P13 establishes; P22 provides real sandbox; all config-loading phases comply |
| **Proactive execution** (scheduler + A2A + Obsidian RAG — §2) | P6/P7/P8 — the differentiated Chief-of-Staff story |
| **Composition & interop** (be composable, not a control plane) | P6 A2A, P17 MCP, P14a AG-UI (archived), P22 meta-harness compat |
| **Identity & trust** (agent IAM, clean-room sharing — ecosystem pillar 3) | P25 establishes AgentIdentity; P26 declassification gateway; P13 credential scoping; P6/P17 carry authn |
| **Feedback loop** (evals, simulation, learning — ecosystem pillars 2+5) | P4 traces (archived); P27 evals + simulation personas + trace→dataset; P28 learns (eval-gated); P7 schedules both |
| **Multimodal I/O** (ecosystem pillar 6) | P29 establishes; P20 supplies local ASR/TTS; P14a (archived) is the transport |

## v3 change log (vs v2)

- Added retroactive rows **P14a `harness-ag-ui-bridge`** (phase; archived
  2026-05-21 without a v2 row — spec-invariant fix) and **X2
  `fix-harness-conversation-memory`** (non-phase; archived 2026-05-15).
- Added new phases **P19–P23** and non-phase **X3** from the 2026-07-07
  architecture review (provenance in Source column).
- **Folded `railway-deployment` (v2 P18, original P10) into P23** as an
  optional cloud variant; the home-lab topology is now primary. No P18
  change directory ever existed, so no archive linkage is broken.
- Reframed **P11** (harness routing only; model routing extracted to P19)
  and **P16** (explicit `codex` registration + `gemini_cli` host harness).
- Multi-model routing, previously in v2's "Out of scope" list, is now in
  scope (P19/P20).
- **2026-07-16 amendment (ecosystem brief)**: added P24
  `capability-protocols-v2` (contracts-only pre-phase for the five seam
  gaps identified in the architecture review) and P25–P29 (`agent-iam`,
  `knowledge-clean-room`, `eval-simulation-loop`, `continual-learning`,
  `multimodal-io`) from
  `docs/architecture-analysis/2026-07-16-ecosystem-pillars.md`. The
  formerly out-of-scope "cross-persona bridge" and "role learning" items
  re-enter as P26 and P28 respectively.

## Out of scope for roadmap v3

Deferred items with no current phase: persona config encryption,
NotebookLM integration, in-repo session-sharing / multi-user control
plane (delegated to meta-harnesses per P22's adopt-not-build posture),
and fully autonomous self-modification (P27/P28 deliberately stop at
propose → eval → human-approved diff). Each may re-enter a future v4
roadmap if demand surfaces. (Cross-persona bridge and role learning,
deferred since v2, re-entered scope on 2026-07-16 as P26 and P28.)
