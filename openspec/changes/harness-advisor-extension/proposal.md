# Proposal: harness-advisor-extension

Roadmap slot: **P1.7** (after P1.6 `patterns-architecture`).
Prerequisite: P1.6 landed — see `openspec/changes/patterns-architecture/design.md`.

## Why

Anthropic's April 2026 advisor tool
([blog](https://claude.com/blog/the-advisor-strategy)) lets a cheap executor
(Sonnet/Haiku) consult Opus on shared context when stuck, yielding +2.7pp
SWE-bench Multilingual and -11.9% cost per task for Sonnet+Opus.

P1.6 `patterns-architecture` established the four-layer model and the
Capability declaration framework. P1.7 is the **first reference
implementation**: it delivers `Capability.ADVISE` end-to-end, proving the
capability model works for a real pattern before P12 (DELEGATE), P2
(MEMORY_SEARCH), and P11 (routing) adopt it.

The existing harness layer has `invoke()` (executor loop) and
`spawn_sub_agent()` (delegation with fresh context) but no shared-context
consultation primitive. Roles like `coder` — single-loop, occasional hard
decisions — are the exact shape the advisor pattern targets.

## What Changes

### Capability framework (first concrete implementation of P1.6)

- **`Capability` StrEnum** in a new `src/assistant/core/capabilities.py`:
  initially `ADVISE = "advise"`. Open for extension — P12 adds `DELEGATE`,
  P2 adds `MEMORY_SEARCH`, etc.
- **`CapabilityInfo` dataclass** in the same module: `mode` (native /
  emulated / transport-mediated / not_supported), `cost_characteristic`
  (cheap / moderate / expensive), optional `notes`.
- **`capabilities` classvar** on each `HarnessAdapter` subclass — a dict
  mapping `Capability` to `CapabilityInfo`. The ABC itself is unchanged
  (no new abstract methods, per P1.6 anti-pattern AP3). Factory reads
  the classvar to check capability match.

### ADVISE pattern implementation

- **`AdvisorClient`** in `src/assistant/core/advisor.py`: wraps the
  `anthropic` SDK directly (bypasses LangChain). Makes a Messages API
  call with the `advisor_20260301` tool type +
  `anthropic-beta: advisor-tool-2026-03-01` header. Accepts the executor's
  full transcript + a question; returns an `AdvisorResponse` (guidance
  text, model identity, token usage, duration_ms).
- **`AdvisorTool`** — a LangChain `StructuredTool` that wraps
  `AdvisorClient`. When the executor LLM emits a `tool_use` for
  `advisor(question=...)`, the tool handler collects the transcript from
  the agent state, calls `AdvisorClient.call()`, and returns the
  guidance as the tool result. The executor resumes with the advice.
- **Deep Agents** declares `Capability.ADVISE` as **native** with
  cost `cheap`. Implementation: the `AdvisorTool` is added to the
  agent's tool list when the role has `required_capabilities: [ADVISE]`.
- **MS Agent Framework** declares `Capability.ADVISE` as **emulated**
  with cost `expensive`. Implementation: a separate Opus API call with
  the transcript passed as a context message. Same `AdvisorResponse`
  contract. Documents the two-roundtrip cost penalty in `notes`.

### Role and persona schema extensions

- **`executor_model`** — optional field on `RoleConfig`. When present,
  overrides `persona.harnesses.<name>.model` for agent creation. Falls
  back to persona-level when absent. Enables the cost story: `coder`
  runs Sonnet even when the persona default is Opus.
- **`required_capabilities`** — list of `Capability` identifiers on
  `RoleConfig`. Factory checks the bound harness satisfies all. Empty
  or absent = bind to any harness (backward-compatible).
- **`advisor:` block** on `RoleConfig` — pattern-specific config: `model`
  (default `claude-opus-4-6`), `trigger` (`on_demand`),
  `max_calls_per_task` (default 3), `budget_tokens` (default 1800).
- Persona role overrides merge the new fields via existing shallow-merge
  semantics (`role.py:34-37`).

### Factory update

- `harnesses/factory.py` gains a capability-match check: before binding
  role to harness, verify the harness's `capabilities` classvar satisfies
  the role's `required_capabilities`. If unmet, raise with a message
  naming the missing capabilities. (Matching algorithm is deferred to P11
  — this is the contract-only check from P1.6 §D5.)

### E2E reference

- **`coder` role** gains `required_capabilities: [ADVISE]`,
  `executor_model: "anthropic:claude-sonnet-4-6"`, and an `advisor:`
  block. Prompt updated with "when to consult the advisor" section.
- **Integration test** stubs the Anthropic API, creates a Deep Agents
  agent with the coder role, simulates a hard-decision turn, and asserts
  the advisor tool is invoked and guidance is returned.

### New dependency

- `anthropic>=0.40` in `pyproject.toml`. Scoped to `advisor.py` only.
  LangChain continues to drive the executor loop.

## Capabilities

### New Capabilities

- `advisor-tool`: `AdvisorClient` + `AdvisorTool`, advisor wire format
  (advisor_20260301, beta header), emulated fallback, LangChain tool
  exposure. Distinct from `harness-adapter` because the Anthropic-specific
  wire format is harness-agnostic infrastructure.

### Modified Capabilities

- `harness-adapter`: Deep Agents + MS AF gain `capabilities` classvars;
  factory gains capability-match check.
- `role-registry`: `RoleConfig` gains `required_capabilities`,
  `executor_model`, `advisor:` block; loader + merge logic updated.

## Impact

- **New files**: `src/assistant/core/capabilities.py` (~50 LOC),
  `src/assistant/core/advisor.py` (~150 LOC).
- **Modified files**: `harnesses/deep_agents.py`, `harnesses/ms_agent_fw.py`,
  `harnesses/factory.py`, `core/role.py`, `roles/coder/role.yaml`,
  `roles/coder/prompt.md` (or `skills/`), `roles/_template/role.yaml`,
  `pyproject.toml`.
- **New dependency**: `anthropic>=0.40`.
- **Tests**: unit tests for `AdvisorClient` (mocked API), `CapabilityInfo`
  declaration, `RoleConfig` schema validation, factory capability matching,
  emulated-fallback parity. Integration test for the full executor → advisor
  → resume loop.
- **Observability hook**: `AdvisorResponse` includes `tokens_in`,
  `tokens_out`, `model`, `duration_ms` so P4 can later add spans.
- **Not affected**: CLI, persona registry, extension registry, prompt
  composition, delegation spawner.

## Approaches Considered

### Approach A — Classvar capability registry + AdvisorTool *(Recommended)*

**Description**: Each `HarnessAdapter` subclass declares a `capabilities`
classvar dict mapping `Capability` → `CapabilityInfo`. The factory reads
this dict for capability matching. `AdvisorClient` (direct Anthropic SDK)
is wrapped as a LangChain `StructuredTool`; the role prompt instructs the
executor when to call it. Capability declarations are colocated with
harness implementations.

**Pros**:
- Capability declarations live next to the code that implements them.
  When reading `deep_agents.py`, you see both the declaration and the
  implementation in one file.
- Classvar dict is the simplest possible registry — no indirection, no
  separate module to maintain, discoverable via `isinstance` check at
  factory time.
- Tool-based escalation keeps the HarnessAdapter ABC unchanged (per AP3).
  The executor loop is unmodified; advisor is just another tool.
- Easy to test: mock `AdvisorClient`, assert the tool handler fires,
  assert guidance is returned as tool result.

**Cons**:
- Two API roundtrips per escalation (executor LangChain call → advisor
  direct-SDK call → executor resumes). Blog's single-call cost numbers
  are not recoverable. Quality gain is preserved; cost gain is partial.
- Adapter modules grow slightly (classvar + imports). Acceptable for 1-2
  capabilities; may need rethinking if a single adapter declares 10+.

**Effort**: **M**.

### Approach B — External capability registry module + AdvisorTool

**Description**: Capability declarations live in a central registry
module (`src/assistant/core/capability_registry.py`) that maps harness
names to `{Capability: CapabilityInfo}` dicts. Adapter classes remain
clean — they don't declare capabilities themselves. Factory queries the
registry, not the adapter.

**Pros**:
- Adapter modules stay focused on agent mechanics.
- A single file shows all capabilities across all harnesses at a glance.
- Adding capabilities to a harness doesn't require modifying the adapter.

**Cons**:
- Declaration is separated from implementation. A reader looking at
  `deep_agents.py` won't know it supports ADVISE without also reading
  the registry. Easy to get out of sync.
- Central registry becomes a coordination bottleneck for parallel changes
  — every capability addition touches the same file.
- More indirection: factory → registry → harness name → CapabilityInfo.

**Effort**: **M**.

### Selected Approach

**Approach A — Classvar capability registry + AdvisorTool.** Confirmed at
discovery. Colocation (declaration next to implementation) is the stronger
property for a repo where harness modules are the primary entry point for
contributors. Approach B's "single-file overview" value is real but
achievable with a CLI command (`openspec list --capabilities`) without
source-level indirection.
