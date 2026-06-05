---

## Phase: Plan (2026-06-05)

**Agent**: claude_code | **Session**: claude/executor-advisor-pattern-NChzx

### Decisions
1. **Capability type: Python StrEnum** -- P1.6 left this conceptual. P1.7
   pioneers `class Capability(StrEnum)` as the concrete representation. All
   later capability proposals (P12 DELEGATE, P2 MEMORY_SEARCH) inherit this
   choice.
2. **HarnessAdapter ABC unchanged; classvar registry alongside** -- Per P1.6
   anti-pattern AP3, no new abstract methods. Each adapter subclass declares
   a `capabilities` classvar dict mapping Capability to CapabilityInfo.
   Factory queries the classvar. Colocation over indirection.
3. **Direct Anthropic SDK for advisor calls** -- LangChain stays as executor
   client. AdvisorClient wraps `anthropic` SDK directly for the
   advisor_20260301 tool type + beta header. Two API roundtrips per
   escalation (quality preserved, cost partial).
4. **Per-role executor_model override** -- RoleConfig gains optional
   executor_model field. Deep Agents uses it instead of persona-level model.
   Enables the cost story: coder runs Sonnet, advisor consults Opus.
5. **Emulated fallback on MS AF** -- Separate Opus call with full transcript.
   Same AdvisorResponse contract. Loses single-call cost advantage.
6. **Tool-based escalation** -- AdvisorClient exposed as LangChain
   StructuredTool. Role prompt drives when the executor calls it.

### Alternatives Considered
- External capability registry module (Approach B): rejected because
  colocating declarations with adapter implementations is more discoverable
  and avoids a coordination bottleneck for parallel changes.
- Growing the HarnessAdapter ABC with an advise() method (original Tier 1):
  rejected per P1.6 AP3 (fat interface anti-pattern).
- Harness-driven turn-boundary escalation: rejected because it requires the
  harness to know LangChain internals (turn boundaries, message injection),
  breaking the opaque agent abstraction.
- LangChain extra_headers passthrough: rejected at original discovery --
  couples to LangChain support for the beta header.

### Trade-offs
- Accepted two API roundtrips per escalation over single-call because
  single-call requires the advisor tool inside the LangChain request
  (ChatAnthropic subclass or extra_headers), which was rejected at discovery.
- Accepted per-role executor_model (larger scope) over advisor-only model
  key because the cost story is unreachable without downshifting the executor.
- Accepted ADVISE-only (not also DELEGATE retrofit) to keep P1.7 scope
  bounded. DELEGATE retrofit comes in P12.

### Open Questions
- [ ] How does AdvisorTool access the full transcript from LangChain agent
  state? The exact mechanism depends on LangGraph node state shape -- needs
  investigation during implementation.
- [ ] Should the coder prompt language for "when to call advisor" be in
  prompt.md or in a skill file under roles/coder/skills/?
- [ ] P4 observability: what span format should AdvisorResponse fields map
  to? Deferred to P4 but the dataclass shape should anticipate it.

### Context
P1.7 is the first reference implementation of P1.6 patterns-architecture.
It delivers Capability.ADVISE end-to-end with two harness implementations
(Deep Agents native, MS AF emulated), proving the capability model works
for a real pattern. The proposal was originally drafted at Tier 1 (add
advise() to HarnessAdapter), paused at Gate 1 when the multi-harness
architectural concern surfaced, and rewritten after P1.6 established the
four-layer model. Approach A (classvar capability registry + AdvisorTool)
selected for colocation and simplicity.
