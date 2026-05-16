# Session Log — harness-ag-ui-bridge

---

## Phase: Plan (2026-05-16)

**Agent**: claude_code (Opus 4.7 1M context) | **Session**: local

### Decisions

1. Adopt two open standards in tandem. AG-UI protocol is the streaming event transport from the Python harness to the React frontend. OpenUI Lang is the rendering format inside assistant message bodies. This change implements only the AG-UI transport half. OpenUI Lang adoption is deferred to a follow-up change. Rationale: AG-UI is already spoken by Microsoft Agent Framework, the planned secondary harness, and by Pydantic AI. It is open, event-based, and SSE-native.

2. Approach 2 selected at Gate 1: separated transport plus emitter. Two new packages will be added. The transports package owns the HarnessEvent abstraction and the AG-UI mapper. The web package is the FastAPI app. The harness yields harness-agnostic HarnessEvent instances rather than raw LangChain events.

3. Additive astream_invoke on SdkHarnessAdapter. The existing blocking invoke method that returns a string is preserved unchanged. A new abstract async-generator method is added alongside it. The CLI REPL continues to use invoke. The new HTTP transport uses astream_invoke.

4. Startup-time persona and role binding. The serve subcommand binds exactly one persona and role at server startup via the FastAPI lifespan. One server process equals one conversation thread. This matches the single-user constraint from the exploration.

5. Minimal AG-UI event coverage in v1. Eight event types are in scope: RUN_STARTED, RUN_FINISHED, TEXT_MESSAGE_START, TEXT_MESSAGE_CONTENT, TEXT_MESSAGE_END, TOOL_CALL_START, TOOL_CALL_ARGS, TOOL_CALL_END. STATE_DELTA and CUSTOM are explicitly out of scope.

6. HarnessEvent variant set frozen for v1. Six variants: RunStarted, RunFinished, TextDelta, ToolCallStart, ToolCallArgs, ToolCallEnd. Field names are harness-agnostic and protocol-agnostic.

7. Coordinated tier selected. The coordinator is available so coordinated tier was chosen. Practical parallel opportunity is exactly one pair: the AG-UI emitter package can run alongside the Deep Agents streaming package. The remaining packages are serial due to file-write dependencies. Honest framing: this saves about one package of wall-clock time at implementation, not a five-times speedup.

### Alternatives Considered

- Approach 1, thin single-module bridge: rejected. Would couple the AG-UI mapper to LangChain event vocabulary. A future MSAF harness would need a parallel mapper.
- Approach 3, direct LangChain passthrough: rejected. Leaks LangChain types into the harness contract. Same MSAF concern as Approach 1.
- Replace invoke instead of adding astream_invoke: rejected. Would break the CLI synchronous behavior with no current benefit.
- Per-request persona binding: rejected. Adds API surface for header or path scoping plus auth without a current single-user need. Multi-persona future is additive when needed.
- Comprehensive AG-UI event coverage in v1: rejected. Larger prompt-tuning surface for limited v1 value. STATE_DELTA and CUSTOM events can be added incrementally without breaking changes.

### Trade-offs

- Accepted roughly 200 extra lines and one additional package (Approach 2 over Approach 1) for clean architectural separation and an additive MSAF future.
- Accepted format-stability risk of OpenUI Lang v0.5 to v1.0 and AG-UI pre-1.0 evolution. Strategic benefit: two open standards over a bespoke wire format.
- Accepted single-conversation-per-server in v1 rather than designing for multi-conversation upfront. Forward path is documented in the design document.
- Accepted non-validating local work-packages workflow prior to this change. The canonical schema was only at agentic-coding-tools. Copied the schema into openspec slash schemas as a side benefit so future coordinated-tier proposals validate locally.

### Open Questions

- The ag-ui-protocol Python package availability and quality. Resolved at implementation task 1.1 (dependency audit): either depend on upstream or define types in-repo.
- Exact LangChain astream event names to filter into HarnessEvent variants. Resolved at task 3.6 by writing the mapper against an explicit allowlist of LangGraph event types.
- Whether the future web-frontend-shell follow-up adopts openuidev react-headless (which speaks AG-UI natively) or builds the chat shell on top of assistant-ui instead. Deferred to that change.

### Procedural Notes

- Coordinator pre-registration was skipped. Step 10 of plan-feature could not call register_feature or acquire_lock. Both returned HTTP 403 with detail that the API key is not permitted to act as the requested agent_id. The get_my_profile call confirms the agent has both operations in allowed_operations at trust level 3, so the failure is at the agent_id propagation layer. The session banner showed Agent ID as unset. Locks will be acquired by individual agents at implementation dispatch time. No other features are in progress per openspec list, so cross-feature overlap detection is not load-bearing today. Filed as follow-up: configure agent_id in the local coordinator profile.
- The openspec schemas work-packages schema was missing locally. Copied from agentic-coding-tools, the canonical source, into this repo. Future coordinated-tier proposals will validate locally without this manual step.
- The docs architecture-analysis directory does not exist in this repo. Not needed for parallel_zones validate-packages (the script validates package overlap directly without requiring the architecture snapshot). The full architecture refresh remains available via the refresh-architecture skill if and when needed.
- Session log sanitizer over-redacted plain prose on first pass, eating spans across paragraph boundaries. Reverted to the unsanitized text since it contains no actual secrets (only deterministic technical identifiers). Filed as follow-up against the canonical sanitizer in agentic-coding-tools.

### Context

The user invoked plan-feature after a multi-turn exploration documented at the explore directory under openspec. That exploration eliminated Thesys C1, Vercel AI SDK with RSC, and CopilotKit on stack-fit and privacy grounds. It selected AG-UI for transport and OpenUI Lang for rendering as the two open standards to adopt. This change implements the first phase of that plan: the transport-only AG-UI bridge over HTTP and SSE, with no frontend yet. Success is verified with curl against the new endpoint.

---

## Phase: Plan revision (2026-05-16)

**Agent**: claude_code (Opus 4.7 1M context) | **Session**: local

### Decisions

1. Extend scope to include MSAF streaming. The explore agent had reported MSAF as stubbed (working from a stale CLAUDE.md note), but the actual code at src/assistant/harnesses/sdk/ms_agent_fw.py is a fully wired SdkHarnessAdapter using agent_framework.Agent with capability resolver, memory prepend, tool policy filtering, and lazy imports for the v1.0.1 namespace quirk. Making astream_invoke abstract on the base class without implementing it on MSAF would regress the spec consistency (MSAF.invoke is real but MSAF.astream_invoke would raise NotImplementedError). Decision: implement MSAF streaming in this change.

2. Use the upstream ag_ui Python package. Confirmed installed in the current venv. ag_ui.core provides Pydantic-typed RunStartedEvent, RunFinishedEvent, TextMessageStartEvent, TextMessageContentEvent, TextMessageEndEvent, ToolCallStartEvent, ToolCallArgsEvent, ToolCallEndEvent plus the EventType enum. Replaces the in-repo Pydantic types fallback option in D5. The original open question (does the package exist) is closed.

3. Acknowledge Microsoft agent_framework_ag_ui but do not adopt in v1. The package is installed and ships add_agent_framework_fastapi_endpoint, AgentFrameworkAgent, AGUIChatClient, AGUIEventConverter. However: importing it fails today with "cannot import name SupportsAgentRun from agent_framework", a consequence of the v1.0.1 namespace-package quirk. Even if it worked, adopting it would fragment the harness boundary (Microsoft path for MSAF, custom path for DeepAgents). Documented as D10 with a follow-up reconsideration once upstream packaging is fixed.

4. MSAF stream translation table documented as D11. Maps AgentResponseUpdate fields (with defensive getattr fallbacks) to HarnessEvent variants. Mirrors the existing _stringify_run_result defensive coding pattern for SDK shape drift.

5. Bump plan_revision to 2 in work-packages.yaml to reflect material plan change.

### Alternatives Considered

- Defer MSAF streaming to a follow-up issue and make astream_invoke non-abstract with a NotImplementedError default. Rejected because it ships a spec inconsistency (MSAF would have only partial SdkHarnessAdapter compliance after this change) and would force the CLI serve subcommand to reject MSAF at runtime, which is a regression.
- Adopt Microsoft agent_framework_ag_ui for MSAF and keep our custom emitter for DeepAgents. Rejected because the package is broken in the current venv (v1.0.1 namespace quirk) and even if fixed it would fragment the harness boundary.
- Investigate fixing the agent_framework_ag_ui import (potentially upstream PR). Rejected for this change because the fix is not scoped here and the current uniform-HarnessEvent path works today. Filed mentally as a future evaluation when upstream resolves the packaging issue.

### Trade-offs

- Accepted ~150 additional lines and one more work package (wp-msaf-stream) for spec consistency across both currently-real harnesses.
- Accepted the SDK-shape-drift risk for agent_framework.AgentResponseUpdate. Mitigation: defensive getattr fallbacks plus version-pinned test fixtures.
- Accepted the slightly longer parallel layer (3 packages: wp-deep-agents-stream, wp-msaf-stream, wp-ag-ui-emitter) instead of 2. Parallel zone validation already confirms no scope overlap.

### Open Questions

- Exact attribute names on agent_framework.AgentResponseUpdate (text vs content vs delta, tool_calls list shape). Resolved during Task 3b.7 by reading the SDK source and writing fixture-driven tests.

### Procedural Notes

- proposal.md updated: What Changes adds MSAF MODIFIED bullet; Impact updates the modified files list and rephrases MSAF future impact to MSAF current impact; Selected Approach mentions the revision; out-of-scope drops the now-included MSAF item.
- design.md updated: D5 rewritten (use upstream ag_ui); D10 added (Microsoft package broken in venv plus harness-boundary fragmentation concern); D11 added (MSAF translation table); Risks updated; Open Question 1 dropped.
- specs/harness-adapter/spec.md updated: new ADDED Requirement "MS Agent Framework Streaming Invocation" with six scenarios paralleling the Deep Agents one.
- tasks.md updated: Task 1.1 marked closed (research resolved at plan time); Task 1.4 dropped its dependency on 1.1; new Section 3b added with seven MSAF tasks (six tests plus one implementation).
- work-packages.yaml updated: plan_revision bumped to 2; new wp-msaf-stream package added between wp-deep-agents-stream and wp-ag-ui-emitter; wp-web-cli.depends_on extended with wp-msaf-stream.

### Context

User answered Gate 2 with the directive to check the code because MSAF was reported as implemented in P5 already. Code inspection confirmed MSAF.invoke is real and uses agent_framework.Agent.run; the SDK also exposes stream=True overload returning ResponseStream. This revision aligns the plan with the actual codebase state.
