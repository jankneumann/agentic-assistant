# Ecosystem Pillars — 2026-07-16

> Owner-provided ecosystem brief (2026-07-16), mapped against the codebase
> and roadmap v3. Companion to
> `2026-07-07-architecture-review.md`; provenance reference for roadmap
> rows P24–P29. Each pillar: current assets → gap → phase assignment.

## Pillar 1 — Model routing (capability + cost aware; cloud + local)

**Assets:** none in code (single `init_chat_model` string per harness).
**Roadmap:** P19 `model-provider-routing`, P20 `local-inference-node`.
**Gap closed here:** P19's scope is sharpened to include a **price/cost
catalog** per model entry (input/output token rates, or `flat-rate` for
subscription seats and `local` for owned compute) so routing can be
cost-aware, not just capability-aware; budget enforcement stays in
`GuardrailProvider` (`ActionRequest(action_type="model_call")`).
**New abstraction:** `ModelProvider` as **capability slot #6** in
`CapabilitySet` (chat + embeddings), specified in P24 and implemented in
P19 — models are today the only cross-cutting concern bypassing the
capability architecture.

## Pillar 2 — Context management: memory + continual learning

**Assets:** `MemoryManager` (Postgres + Graphiti) real; retrieval inert
(all `MemoryPolicy.get_recent_snippets()` return `[]`); three-layer
prompt composition; `memory.md` convention.
**Roadmap:** P21 `memory-retrieval-activation` covers the retrieval half.
**Gap:** nothing *learns*. No consolidation, no feedback capture, no
preference distillation. Role learning was explicitly out of scope in
v2/v3.
**Phase:** **P28 `continual-learning`** — (a) scheduled reflection/
consolidation jobs (Graphiti episodes → semantic facts → regenerated
`memory.md` prompt layer), (b) explicit feedback capture as first-class
events (CLI + AG-UI thumbs/corrections → `interactions` table),
(c) preference distillation into the persona prompt layer, (d) role
learning re-scoped here as prompt-layer suggestions. **Every learned
change is eval-gated (P27) and lands as a reviewable diff in the persona
submodule — git is the approval workflow; no silent self-modification.**

## Pillar 3 — P2P + central orchestration, agent IAM, clean-room sharing

**Assets:** delegation spawner (in-process only); AG-UI server; A2A (P6)
and MCP (P17) planned; meta-harness posture (P22). Test-time privacy
boundary between personas is enforced by the two-layer guard.
**Gap A — Agent IAM:** no notion of an agent *principal*. Everything
runs with ambient credentials.
**Phase:** **P25 `agent-iam`** — an `AgentIdentity` (persona, role,
delegation chain, session) attached to every `ActionRequest`, every
delegation hop (P12's `delegation_chain` becomes signed/attributable),
and every inbound/outbound A2A/MCP call (agent-card auth on the server
surfaces; scoped, per-persona short-lived credentials on the client
side). Extends — does not replace — P13's env-var scoping.
**Gap B — Clean-room knowledge sharing:** cross-persona exchange is
banned at test time but *undefined* at runtime; the bootstrap's
"cross-persona bridge" was deferred with no design.
**Phase:** **P26 `knowledge-clean-room`** — a **declassification
gateway**: policy-driven, audited flow `source persona memory →
sanitization (reuse telemetry/sanitize.py PII machinery) → shared
knowledge space → consuming persona`, with per-fact provenance and
revocation. The runtime analogue of the existing test-time privacy
boundary; also the trust story for sharing knowledge with *external*
agents (A2A peers, meta-harness co-agents).

## Pillar 4 — Sandbox concepts (FS, API/credentials, network)

**Assets:** `SandboxProvider` protocol exists but models only a
`work_dir` and is **consumed by nobody** — no enforcement seam.
**Phases:** **P24 `capability-protocols-v2`** specifies `SandboxConfig`
v2 with three planes — filesystem (workdir, ro/rw mounts), network
(deny-by-default egress allow-lists, proxy), credentials (which env
vars/secrets a session sees — joint with P13) — and names the
enforcement seam (tool invocation + extension subprocess boundary).
P22 implements the first real provider (container/OpenShell-backed,
NemoClaw-aligned); P13 wires credential scoping.

## Pillar 5 — Evals, observability, API simulation → closed feedback loop

**Assets:** Langfuse tracing with token/cost capture (P4, archived);
`gen-eval` adopted (2026-05-21) with `evaluation/` scenarios +
descriptors; rich API-mock assets (`tests/mocks/graph_client.py`,
`tests/fixtures/graph_responses/`, pytest-httpserver suites) — currently
test-only.
**Gap:** the assets don't form a loop. No standing behavioral eval suite
per role, no runtime API simulation, no trace→dataset pipeline.
**Phase:** **P27 `eval-simulation-loop`** —
(a) **Simulation personas**: a persona whose `tool_sources` point at
simulator endpoints (promote the test mocks to a runnable
`assistant simulate` surface) — reusing persona-as-execution-boundary
means zero new agent code paths for simulation;
(b) per-role gen-eval scenario suites run against simulation personas
(CI + scheduled);
(c) trace→dataset: export Langfuse traces into eval datasets, so
regressions found in production conversations become permanent tests;
(d) the improvement loop: eval results gate P28's learned changes and
any prompt/routing config change. "Recursive self-improvement" is
implemented as **propose → eval → human-approved diff**, never
self-merge.

## Pillar 6 — Multimodal interfaces (data + user)

**Assets:** text-only CLI and AG-UI SSE. `openspec/explore/generative-ui-layer.md`
already selected AG-UI + OpenUI Lang for generative UI.
**Phase:** **P29 `multimodal-io`** — (a) extend the `HarnessEvent`
vocabulary and AG-UI mapping with typed multimodal parts (image, audio,
file/document) in and out; (b) voice: local ASR/TTS on the GX10 (P20
synergy — Whisper-class + TTS as local model-registry entries) behind
the same event vocabulary; (c) document/image ingestion routed through
extensions into memory/ACA indexing; (d) generative-UI rendering
(OpenUI) as the data-facing modality, picking up where the explore doc
left off. Sequenced late: every earlier pillar multiplies its value.

## Cross-pillar dependencies (summary)

```
P24 contracts ─→ P19 ─→ P20 ─┬─→ P29 (local ASR/TTS)
                             └─→ P27 cheap eval runs / P28 cheap reflection
P21 memory activation ─→ P28 continual-learning ←─ P27 eval gate ←─ P4 (archived)
P6/P17 interop ─→ P25 agent-iam ─→ P26 clean-room ←─ P21
P24 sandbox planes ─→ P22 (real provider) / P13 (credential plane)
```
