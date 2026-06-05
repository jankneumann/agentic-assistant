# Tasks: harness-advisor-extension

## Phase 1 — Capability Framework Types

- [ ] 1.1 Write tests for Capability StrEnum and CapabilityInfo dataclass
  **Spec scenarios**: harness-adapter.1 (capability declaration classvar),
  harness-adapter.2 (undeclared defaults to not_supported)
  **Design decisions**: D1 (StrEnum + frozen dataclass + NOT_SUPPORTED sentinel)
  **Dependencies**: None

- [ ] 1.2 Create `src/assistant/core/capabilities.py` — Capability StrEnum,
  CapabilityInfo dataclass, NOT_SUPPORTED sentinel
  **Dependencies**: 1.1

## Phase 2 — AdvisorClient + AdvisorResponse

- [ ] 2.1 Write tests for AdvisorClient — mock Anthropic Messages API, verify
  advisor_20260301 tool type + beta header, verify full transcript is passed
  (never summarized), verify budget_tokens caps response not input
  **Spec scenarios**: advisor-tool.1 (full transcript), advisor-tool.2
  (never summarized), advisor-tool.3 (budget caps response)
  **Design decisions**: D2 (direct SDK bypass), D3 (two-roundtrip acknowledgment)
  **Dependencies**: 1.2

- [ ] 2.2 Add `anthropic>=0.40` to `pyproject.toml` dependencies
  **Dependencies**: None

- [ ] 2.3 Create `src/assistant/core/advisor.py` — AdvisorClient class
  with call() method, AdvisorResponse dataclass
  **Dependencies**: 2.1, 2.2

## Phase 3 — Role Schema Extensions

- [ ] 3.1 Write tests for RoleConfig — required_capabilities parsing,
  executor_model override, advisor block parsing + defaults + validation
  **Spec scenarios**: role-registry.1 (required_capabilities field),
  role-registry.2 (executor_model override), role-registry.3 (advisor block)
  **Design decisions**: D4 (per-role executor model)
  **Dependencies**: 1.2

- [ ] 3.2 Update `src/assistant/core/role.py` — add required_capabilities,
  executor_model, advisor fields to RoleConfig; update loader and merge logic
  **Dependencies**: 3.1

## Phase 4 — Harness Capability Declarations + Factory

- [ ] 4.1 Write tests for harness capability declarations — Deep Agents native
  ADVISE, MS AF emulated ADVISE, factory capability-match check (pass + fail)
  **Spec scenarios**: harness-adapter.3 (Deep Agents native), harness-adapter.4
  (MS AF emulated), harness-adapter.5 (factory match), harness-adapter.6
  (factory reject)
  **Design decisions**: D5 (emulated fallback), D6 (factory contract check)
  **Dependencies**: 1.2, 3.2

- [ ] 4.2 Update `src/assistant/harnesses/deep_agents.py` — add capabilities
  classvar with ADVISE native; use executor_model from role when present
  **Dependencies**: 4.1

- [ ] 4.3 Update `src/assistant/harnesses/ms_agent_fw.py` — add capabilities
  classvar with ADVISE emulated
  **Dependencies**: 4.1

- [ ] 4.4 Update `src/assistant/harnesses/factory.py` — add capability-match
  check before harness binding
  **Dependencies**: 4.1

## Phase 5 — AdvisorTool + E2E Integration

- [ ] 5.1 Write tests for AdvisorTool — tool invocation collects transcript,
  calls AdvisorClient, returns guidance as tool result; opt-in check (no
  advisor block = no tool added)
  **Spec scenarios**: advisor-tool.4 (tool invocation), advisor-tool.5 (opt-in)
  **Design decisions**: D3 (LangChain StructuredTool wrapping)
  **Dependencies**: 2.3, 3.2

- [ ] 5.2 Create AdvisorTool in `advisor.py` (or separate module) — LangChain
  StructuredTool wrapping AdvisorClient; wire into Deep Agents create_agent()
  when role has ADVISE capability
  **Dependencies**: 5.1

- [ ] 5.3 Update `roles/coder/role.yaml` — add required_capabilities: [ADVISE],
  executor_model, advisor block
  **Dependencies**: 3.2

- [ ] 5.4 Update `roles/coder/prompt.md` (or skills/) — add "when to consult
  the advisor" prompt section
  **Dependencies**: 5.3

- [ ] 5.5 Update `roles/_template/role.yaml` — add commented-out advisor block
  as reference for new roles
  **Dependencies**: 3.2

- [ ] 5.6 Write E2E integration test — create Deep Agents agent with coder role,
  stub Anthropic API, simulate hard-decision turn, assert advisor tool is
  invoked, assert guidance is returned and executor resumes
  **Spec scenarios**: advisor-tool.4 (tool invocation during agent loop)
  **Design decisions**: D2 (AdvisorClient), D3 (AdvisorTool), D6 (factory match)
  **Dependencies**: 5.2, 5.3, 5.4, 4.2, 4.4

## Phase 6 — Emulated Fallback Parity

- [ ] 6.1 Write tests for emulated advisor path — same AdvisorResponse shape,
  full transcript passed, no summarization
  **Spec scenarios**: advisor-tool.6 (emulated same shape), advisor-tool.7
  (emulated full transcript)
  **Dependencies**: 2.3, 4.3

- [ ] 6.2 Implement emulated advisor in MS Agent Framework adapter — standalone
  AdvisorClient call with transcript as context
  **Dependencies**: 6.1
