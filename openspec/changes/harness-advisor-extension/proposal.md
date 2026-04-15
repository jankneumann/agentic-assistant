# Proposal: harness-advisor-extension

Roadmap slot: **P1.7** (inserted before P2 per `openspec/roadmap.md`).

---

> **⚠️ STATUS: DRAFT — AWAITS P1.6 `patterns-architecture`**
>
> This proposal was drafted at Tier 1 scope (advisor-only, `HarnessAdapter`
> gains a fourth abstract method). During Gate 1 review the direction was
> revised to **Tier 3**: a prerequisite architectural-framing proposal
> (`patterns-architecture`, slotted as P1.6) must land first, and this
> proposal will be rewritten as the **first reference implementation** of
> that framing.
>
> Expected revisions once P1.6 lands:
> - Reframe from "add `advise()` method to `HarnessAdapter`" to
>   "implement `Capability.ADVISE` for two harnesses per the P1.6 pattern
>   protocol."
> - Replace "Approaches Considered" (A/B/C escalation strategies) with
>   the capability-info declaration per harness (`native` / `emulated` /
>   `not_supported` + cost characteristics).
> - Add explicit transport-mediated mode declaration (deferred to P6 A2A
>   landing) so when that transport exists, cross-harness advisor calls
>   Just Work.
> - Reconcile the "new capability: `advisor-tool`" decision against the
>   P1.6 framing — likely becomes `Capability.ADVISE` + per-harness impl
>   modules, not a separate spec capability.
>
> The content below reflects the Tier 1 thinking and is preserved for
> context + as a starting point. Do not implement from this version.

---

## Why

Anthropic's April 2026 advisor tool ([blog](https://claude.com/blog/the-advisor-strategy))
lets a cheap executor model (Sonnet/Haiku) consult Opus on shared context when
it hits a hard decision, yielding reported wins of +2.7pp SWE-bench Multilingual
**and** -11.9% cost per task (Haiku+Opus-advisor: +21.5pp on BrowseComp).

This repo's harness layer currently has two escalation primitives — `invoke()`
for the executor loop and `spawn_sub_agent()` for delegation — but no
shared-context consultation. Roles like `coder` (single-loop, occasional hard
decision) are the exact shape the advisor pattern targets, yet today they
must run entirely on whatever model `persona.harnesses.deep_agents.model`
specifies (see `src/assistant/harnesses/deep_agents.py:23`). Landing an
`advise()` primitive before P2 means `memory-architecture` retrieval paths
can opt in from day one rather than be retrofitted.

The pattern is not delegation: delegation spawns a fresh-context sub-agent to
do work; the advisor reads the executor's full transcript and returns
guidance (400–700 tokens) that the executor acts on. Conflating the two
would muddy `DelegationSpawner`'s abstraction — hence a separate primitive.

## What Changes

- Add `advise(question, context?) -> AdvisorResponse` to the `HarnessAdapter`
  ABC alongside `invoke()` and `spawn_sub_agent()`.
- Implement `advise()` on `DeepAgentsAdapter` using a new `AdvisorClient` that
  bypasses LangChain and calls the raw Anthropic Messages API directly with
  the `advisor_20260301` tool type and `anthropic-beta: advisor-tool-2026-03-01`
  header. Shared-context: the full executor transcript is passed in the request.
- Implement `advise()` on `MSAgentFrameworkAdapter` as an **emulated fallback**:
  a separate Opus call with the transcript passed as a context message. Same
  `AdvisorResponse` contract; documents the cost-advantage loss in a docstring.
- Add an `advisor:` block to the `RoleConfig` schema with keys:
  `model` (default `claude-opus-4-6`), `trigger` (`on_demand` | `on_error`),
  `max_calls_per_task` (int, default 3), `budget_tokens` (int, default 1800).
- Add an optional `executor_model` field to `RoleConfig` so roles can
  downshift below `persona.harnesses.deep_agents.model` (e.g., `coder` runs on
  Sonnet even when the persona default is Opus). Without this, the cost story
  is unreachable.
- Create `src/assistant/core/advisor.py` with `AdvisorClient` (direct
  `anthropic` SDK). Kept separate from `DelegationSpawner`: different
  semantics (shared vs fresh context, guidance vs work).
- Add `anthropic>=0.40` to `pyproject.toml` dependencies. LangChain continues
  to drive the executor loop; the SDK is scoped to advisor calls.
- Expose `AdvisorClient` as a LangChain tool (see Approach A) that roles can
  include via their `preferred_tools`. Role prompt language in
  `roles/_template/prompt.md` gains a section explaining when to call the
  advisor.
- Wire **one concrete E2E path**: `coder` role opts in with an `advisor:`
  block; integration test stubs the Anthropic API and asserts the advisor
  tool is invoked during a simulated hard-decision turn.
- Add `docs/gotchas.md` entry: "Advisor ≠ delegation; never summarize the
  transcript before an advisor call" (the summarization anti-pattern
  discussed in the related Claude Code session).

Opt-in per role; roles without an `advisor:` block have unchanged behavior.
Not BREAKING — the ABC gets a default `raise NotImplementedError` stub for
backwards compatibility with any out-of-tree harness adapters.

## Capabilities

### New Capabilities

- `advisor-tool`: Direct-SDK `AdvisorClient`, advisor-tool-specific wire
  format (advisor_20260301, beta header), emulated-fallback behavior for
  non-Anthropic harnesses, LangChain-tool exposure. This is a distinct
  capability because the Anthropic-specific wire format doesn't belong in
  `harness-adapter` (which is harness-agnostic).

### Modified Capabilities

- `harness-adapter`: Adds a fourth abstract method, `advise()`, with contract
  requirements on shared-context semantics and `AdvisorResponse` shape.
- `role-registry`: `RoleConfig` loader gains optional `advisor:` block
  parsing + `executor_model` field; validation rejects malformed advisor
  blocks.

### Intentionally Unchanged

- `delegation-spawner`: Advisor is NOT a delegation. No changes.
- `persona-registry`: Model selection at `persona.harnesses.*.model` stays
  intact; `executor_model` layers on top via the existing shallow-merge
  override path.

## Impact

- **New code**: `src/assistant/core/advisor.py` (~150 LOC), wiring in
  `src/assistant/harnesses/deep_agents.py` and `ms_agent_fw.py`,
  `RoleConfig` schema updates in `src/assistant/core/role.py`.
- **New dependency**: `anthropic>=0.40` (direct SDK). Scope-contained to
  `advisor.py`.
- **Configuration**: `roles/coder/role.yaml` gains an `advisor:` block as
  the E2E reference. Template updated in `roles/_template/role.yaml`.
- **Tests**: Unit tests for `AdvisorClient` (mocked Messages API),
  `RoleConfig` schema validation, emulated-fallback parity test. Integration
  test demonstrating Deep Agents → advisor → resume loop.
- **Observability hook**: `advise()` records `tokens_in`, `tokens_out`,
  `model`, `duration_ms` in an `AdvisorCallLog` dataclass so P4 can later
  add spans without re-plumbing.
- **Docs**: `docs/gotchas.md` anti-pattern entry; `openspec/roadmap.md`
  already reflects the P1.7 slot (committed earlier on this branch).
- **Downstream adopters** (future, not in this proposal): P2
  memory-architecture retrieval, P4 observability span wiring, P11
  harness-routing (advisor-capable roles prefer Deep Agents).
- **Not affected**: CLI interface, persona registry, extension registry,
  prompt composition, delegation spawner.

## Approaches Considered

### Approach A — Tool-based escalation *(Recommended)*

**Description**: `AdvisorClient` is exposed to the executor as a standard
LangChain tool named `advisor`. The role's system prompt instructs: "when
stuck on a design decision or after 2 failed tool calls in a row, call
`advisor(question=...)` with the question." When the LLM emits a tool_use
for `advisor`, the tool handler calls `AdvisorClient.call(transcript,
question)`, which makes a direct Messages API request including the
`advisor_20260301` tool + beta header. The advisor's response is returned
as the tool result; the executor resumes.

**Pros**:
- Simplest integration path. No modifications to the Deep Agents / LangChain
  tool loop — advisor is just another tool.
- The role (via its prompt) decides when to escalate, keeping agency with the
  LLM. Matches the blog's "executor escalates" narrative.
- Easy to test: mock `AdvisorClient`, assert the tool handler fires, assert
  tool result is re-injected into the next turn.
- LangChain tool exposure means advisor calls show up in existing LangChain
  traces (relevant for P4 later).

**Cons**:
- Two API round trips per escalation (executor's LangChain call → advisor's
  direct-SDK call → executor's next LangChain call). The blog's exact
  single-call cost numbers are not recoverable with this architecture.
  The quality benefit of shared context is preserved; the cost benefit is
  partial. We accept this because the user chose "Bypass LangChain for
  advisor only" (Gate 1 question) over the approaches that would permit
  single-call.
- Executor must be trained via prompt to call the advisor, which is less
  deterministic than a heuristic trigger (cf. Approach B).

**Effort**: **M** — `advisor.py` + tool wiring + role prompt + one role
adoption + integration test.

### Approach B — Harness-driven turn-boundary escalation

**Description**: `HarnessAdapter.invoke()` wraps the LangChain agent loop
and, at turn boundaries, inspects state (tool_use errors, repeated-message
detection, token budget thresholds). On trigger match, the harness calls
`AdvisorClient.call()` itself and injects the advice as a system message
before the next turn. The role's `advisor:` block configures which triggers
fire (`on_error`, `on_loop`, `on_budget`).

**Pros**:
- Deterministic escalation — cost caps actually enforced at the harness.
- Role authors don't need to prompt-engineer the executor to call the
  advisor; it just happens.
- Testable via trigger simulation without needing a live LLM.

**Cons**:
- The harness becomes aware of LangChain internals (turn boundaries, message
  injection) — violates the current `HarnessAdapter` abstraction that treats
  the underlying agent as opaque.
- Heuristic triggers are hard to tune. "Repeated message" and "budget"
  thresholds will cause false positives and need per-role calibration.
- The LLM loses agency to decide it's stuck — a surprisingly common
  failure mode is the executor *knowing* it needs help but the heuristic
  not firing.

**Effort**: **L** — harness-loop wrapping + trigger library + configuration
surface + per-trigger tests + per-role tuning.

### Approach C — Hybrid (tool + optional heuristic triggers)

**Description**: Combine A and B. Roles declare `advisor.trigger:
[on_demand, on_error]` to enable both — the tool is always available, and
turn-boundary triggers fire in addition when configured.

**Pros**:
- Most flexible. Roles can start with pure `on_demand` (Approach A
  behavior) and add heuristic triggers later.
- Future-proof: if Approach B's triggers prove themselves, roles migrate
  without a spec change.

**Cons**:
- Largest scope for P1.7. Implements both the tool path AND harness-loop
  wrapping.
- Two interacting escalation paths — potential for double-escalation bugs
  (executor calls advisor via tool *and* harness triggers on error in same
  turn).
- YAGNI: we have zero data about whether Approach B's heuristic triggers
  actually help before we've even shipped Approach A.

**Effort**: **L** — sum of A + B + interaction tests.

### Recommendation

**Approach A.** It delivers the pattern's quality story (shared-context
Opus consultation for Sonnet executors) at the lowest architectural risk,
without touching Deep Agents / LangChain internals. The partial cost story
(two round trips instead of one) is an honest consequence of the
"bypass LangChain for advisor" decision and worth documenting rather than
hiding behind complexity.

Approach B can be added in a follow-up proposal *once we have real data*
from Approach A showing where LLM-initiated escalation fails (e.g.,
executor loops without calling the advisor, or escalates too eagerly).
Approach C is Approach A + Approach B done together prematurely — rejected
on YAGNI grounds.
