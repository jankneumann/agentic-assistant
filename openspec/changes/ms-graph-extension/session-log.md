# Session Log — ms-graph-extension

---

## Phase: Plan (2026-05-05)

**Agent**: claude_code Opus 4.7 | **Session**: autopilot P5 invocation

### Decisions

1. **Approach A.2 selected — Transport-interface Protocol with custom MS implementation.** A new CloudGraphClient Protocol in core/cloud_client.py defines the transport shape. The module core/graph_client.py is a custom httpx implementation that satisfies the Protocol and integrates with P9 resilience. This buys cheap optionality for P14 google-extensions (which can choose between custom and SDK-wrapped backends) without committing P5 to wrap a vendor SDK.

2. **MSAL flow uses two pluggable strategies.** InteractiveDelegatedStrategy covers interactive plus silent for delegated user identity. ClientCredentialsStrategy covers app-only for unattended jobs. The driving constraint is Entra ID with SSO as the primary auth target in the work persona deployment context. Device-code is a fallback when the env var MSAL_FALLBACK_DEVICE_CODE equals 1, not a first-class strategy.

3. **MSAF SDK is agent-framework** (PyPI package: agent-framework, repo: microsoft/agent-framework). Confirmed via Context7. Async-native, model-agnostic with OpenAIChatClient or AzureOpenAIChatClient, tools registered as plain Python functions decorated with the ai_function decorator. Different shape from Deep Agents which uses LangChain StructuredTool. Extensions emit tools via two methods (as_langchain_tools and as_ms_agent_tools) rather than going through a converter.

4. **API surface is read-heavy MVP plus narrow writes.** Reads across all four extensions. Writes restricted to outlook.send_email and teams.post_chat_message. SharePoint writes, calendar event creation, and Teams meeting creation deferred to P5b.

5. **Test strategy uses respx plus typed MockGraphClient plus opt-in integration suite.** Unit-level tests mock httpx with respx. Extension-level tests substitute the CloudGraphClient Protocol entirely via MockGraphClient. The opt-in integration suite gated on RUN_GRAPH_TESTS equal 1 hits real Graph for smoke checks. CI runs only the first two layers.

6. **Personal persona stays opted out.** The file personas/personal/persona.yaml does NOT enable any of the four MS extensions in P5. The change ships extensions as code only. P15 work-persona-config is the consumer that lights them up.

7. **No msal[broker] PyWAM. Web-interactive only.** Cross-platform browser flow on every OS. Saves a Windows-specific test matrix and a heavier dep.

8. **Per-persona token cache file at personas/<name>/.cache/msal_token_cache.json with mode 0o600** plus atomic tmp+rename writes plus permission audit on read. Persona is the auth boundary. No global cache.

9. **Six implementation work packages plus an integration package.** wp-foundation gates the four extension packages and the harness package. The four extensions plus the harness run in parallel after foundation lands. wp-integration runs serially at the end to update existing tests, fix the P4 roadmap drift, and run the full quality gate.

### Alternatives Considered

- **A.1 — pure custom httpx, no Protocol layer**: rejected because P14 google-extensions would duplicate the same shape with no shared mental model, and a future SDK swap would require rewriting all extensions.
- **A.3 — wrap msgraph-sdk now**: rejected for P5 because Kiota retry middleware competes with our P9 layer, dep weight is meaningful, and Kiota fluent-API mocking is uglier than httpx mocking. The Protocol shape leaves the door open for retroactive A.3 retrofit if P14 finds it pays off for Google.
- **semantic-kernel for the harness**: rejected because the layered abstractions (kernel, plugins, planners) are heavier than the flat Agent plus tools shape MSAF offers, which fits SdkHarnessAdapter more directly.
- **microsoft/agents-for-python (M365 Agents SDK)**: rejected because it targets building bots inside Teams or Copilot Studio, not building local agents that consume Graph data.
- **Single global token cache at the home cache directory**: rejected because it crosses persona boundaries. A personal-tenant token could end up readable to a work-persona session.
- **Scope choice option 2 (vertical slice ms_graph plus outlook only, defer teams plus sharepoint)**: rejected by the user in favor of the full four-extension scope.

### Trade-offs

- **Accepted about one day of serial foundation work over pure parallelism.** The A.2 foundation must land before extensions, costing maybe a day before the four extension packages and the harness package fan out. In exchange we get one auth implementation, one transport, one resilience integration, and one breaker namespace pattern instead of four to five duplicates.
- **Accepted dual tool-format authoring over a central converter.** Each extension authors tools twice (LangChain plus MSAF). A central converter would have to introspect Pydantic args_schema and re-emit Annotated parameter declarations, which hides parameter docs and produces less precise tool descriptions. Authoring twice is about 20 lines per tool with cleaner output in both ecosystems.
- **Accepted no-MemoryPolicy in MSAF harness for P5.** Bolting memory on with brittle prompt injection now would either lock us into a contract that agent-framework does not yet expose, or paper over the Memory contract. Better to ship MSAF without memory in P5 and add a follow-up issue.

### Open Questions

- [ ] The agent-framework exact version pin: deferred to wp-foundation task 1.16 and wp-msaf-harness task 6.8. Context7 will be queried for current stable at implementation time.
- [ ] Which chat client (OpenAIChatClient vs AzureOpenAIChatClient) the integration test exercises: decided at integration-test authoring time based on which credential set the CI account has.
- [ ] Whether to retroactively wrap msgraph-sdk (Approach A.3 retrofit) if P14 google-extensions chooses to wrap google-api-python-client for symmetry: captured as a P14 design.md open question.

### Tooling Drift Notes

- **The make target named architecture does not exist in this repo.** The plan-feature skill command is generic. The actual refresh is provided by the script at .claude/skills/refresh-architecture/scripts/refresh_architecture.sh. We used the script directly. Future planners should expect the same.
- **The work-packages.schema.json is bundled in agentic-coding-tools/openspec/schemas/ but not in this repo.** The skill validator validate_work_packages.py with the check-overlap flag expects a newer schema shape (with feature and contracts blocks at top level) that the archived examples in this repo do not follow. We skipped schema-based validation. We relied on openspec validate strict (which passes) plus archived-example precedent. Same applies to parallel_zones.py with the validate-packages flag.
- **Coordinator API key lacks register_feature and acquire_lock permission with the unset agent_id.** Both calls return http_403 with the message about the API key not being permitted to act as the requested agent_id. The bootstrap output showed Agent ID unset. Pre-registering planning-intent locks (skill Step 10) was skipped. Implementation-time locks will succeed once the implementing agent has its own valid agent_id. Suggest fixing in a coordinator bootstrap pass. Not a P5 concern.
- **The session-log sanitizer over-redacts plain prose with contractions and possessive apostrophes.** Per the user memory entry feedback_session_log_sanitizer, this is a known issue. This entry was rewritten without contractions and skip the second sanitizer pass.

### Context

The planning goal was to produce all OpenSpec artifacts (proposal, design, specs, tasks, contracts, work-packages, session-log) for P5 of the agentic-assistant roadmap. P5 implements real ms_graph and outlook and teams and sharepoint extensions plus a full MS Agent Framework harness, with Entra ID plus SSO as the primary auth target since the work persona is the primary consumer. Functional prereqs (P3 http-tools-layer, P1.8 capability-protocols, P9 error-resilience) all archived. Six discovery questions answered with all-recommended options. One direction question answered with a hybrid that produced sub-approach A.2 (Protocol-with-custom-MS-impl). The plan validates openspec validate strict clean. Awaiting Gate 2 user approval before transitioning to implement-feature.

---

## Phase: Plan-review (2026-05-05)

**Agent**: claude_code Opus 4.7 (orchestrator) + codex gpt-5.5 + gemini auto | **Session**: parallel-review-plan dispatch + consensus synthesis

### Findings before remediation

| Source | Critical | High | Medium | Low | Total |
|---|---|---|---|---|---|
| claude (self-review) | 0 | 2 | 6 | 4 | 12 |
| codex | 0 | 5 | 5 | 1 | 11 |
| gemini | 0 | 0 | 2 | 2 | 4 |
| **Combined unique** | 0 | 8 | ~12 | ~6 | ~26 |

Quorum 2 of 2 received. Both vendor dispatches succeeded (codex 161s, gemini 54s).

### Multi-vendor agreement (3 reviewers)

- **A**: 429 Retry-After header not honored (claude 2 + codex 6 + gemini 1)
- **B**: Missing transport-level observability span (claude 4 + codex 10 + gemini 3, with gemini adding the request-id correlation detail)

### Cross-vendor agreement (2 reviewers)

- **C**: No per-request httpx timeout specified (claude 3 + gemini 2)
- **D**: download_document return type contradicts dict-only Protocol (codex 2 high + gemini 4 low)

### Codex-unique HIGH findings (vendor-specific MS Graph wire knowledge)

- **E**: PersonaRegistry.load_extensions calls factories with one arg, but new factory contract specified two — broken in production
- **F**: outlook.send_email returns HTTP 202 with empty body on success; spec required parsed JSON
- **G**: GraphAPIError outside the httpx.HTTPStatusError hierarchy — P9 retry classifier never matched, retries silently never fired
- **H**: Retry on non-idempotent POSTs would cause duplicate emails plus duplicate Teams chat messages

### Decisions made during remediation

1. **Adopt all 8 high findings as fixes.** Each becomes a normative spec requirement (D13–D27).
2. **download_document approach**: extend CloudGraphClient Protocol with a fifth method get_bytes (50 MiB cap, streaming, tempfile result). The asymmetry with P14 is acceptable because the same Protocol shape can also serve Google Drive downloads.
3. **MSAF MemoryPolicy**: add minimal memory injection (50 LOC, prepend last N memory snippets to instructions parameter). Closes the asymmetry with DeepAgents harness without waiting for an upstream agent-framework hook.
4. **Factory contract migration**: `create_extension(config, *, persona=None)` keyword-only, with default None, so stubs (gmail/gcal/gdrive) and third-party persona-submodule extensions stay backward-compatible. The four real factories use persona to construct MSAL plus GraphClient internally.
5. **GraphAPIError compatibility**: subclass httpx.HTTPStatusError so P9 classifier matches it without changes to P9.
6. **Per-method retry safety**: `retry_safe: bool = True` parameter on post and on the Protocol; write tools opt out.

### Remediation scope

- 5 spec files modified to add requirements (graph-client gained 8, msal-auth gained 4 including the to_thread wrapping and gitignore check, ms-extensions gained 4 including url-encoding and scope-replace and breaker-error and download_document update, ms-agent-framework-harness gained 1 for memory injection, extension-registry gained 1 for the factory contract)
- design.md gained sections D13 through D27 documenting the post-review additions
- tasks.md gained section 8 with about 30 new tasks across foundation, the four extensions, the MSAF harness, and integration
- work-packages.yaml LOC estimates bumped from 3000 to 4200 across the 6 packages, max_loc cap raised, lock keys and write_allow scopes updated

### Open Questions

- [ ] Whether to also add Microsoft Graph batch endpoint support (graph.microsoft.com/v1.0/$batch) for higher-throughput operations: deferred to P5b. Not raised by review but adjacent to performance findings.
- [ ] Whether the trace_graph_call observability hook should also emit a normalized cost-attribution metric (request count per extension per persona): deferred to P4 follow-up.

### Tooling Notes

- The consensus_synthesizer reported 0 confirmed findings. Inspection showed this is a tooling false negative: its description-text similarity matcher does not cluster claude+codex+gemini findings that describe the same gap with different prose (for example "missing 429 Retry-After" vs "honor Retry-After" vs "respect Retry-After header"). Manual topical synthesis was performed in the orchestrator response. Worth filing an upstream issue against the synthesizer for fuzzy or topical matching.
- Three vendors all spent meaningfully different time on the review (claude self-review during authoring, codex 161s, gemini 54s). Codex produced the most thorough review with vendor-specific MS Graph wire knowledge that the orchestrator (claude) lacked. This validates the parallel-review-plan design intent: orchestrator blind spots get caught by independent reviewers.
