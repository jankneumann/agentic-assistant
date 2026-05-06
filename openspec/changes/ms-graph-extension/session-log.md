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

---

## Phase: Plan Iteration 1 (2026-05-05)

**Agent**: claude_code Opus 4.7 1M | **Session**: autopilot P5 PLAN_ITERATE phase

### Decisions

1. **Five parallel Explore agents synthesized 33 raw findings; net 14 actionable after dedup and quality filter.** Across completeness, clarity-consistency, feasibility-parallelizability, testability, security-performance dimensions. Threshold medium. Five findings rejected as questionable (Python string zero-out via os.urandom, exact string equality for memory snippet format, regex JWT pattern for token validity, retry_safe linting tooling, docs-must-be-in-spec).

2. **D19 cleanup as one logical group.** Round-1 remediation expanded the CloudGraphClient Protocol to five methods (added get_bytes via D19) but left three downstream stale references: design.md D3 code example showed only four methods, tasks.md task 1.1 cited the obsolete scenario name "Protocol declares four required methods", task 1.2 listed only four method names. All three resolved in this iteration.

3. **Rejected the feasibility agent's critical pyproject.toml dual-ownership finding.** wp-msaf-harness explicitly depends on wp-foundation, so the dep edge already serializes pyproject lock acquisition. The four extension packages that DO run parallel with harness do not edit pyproject.toml. Strengthened the existing lock comment to make this serialization explicit, and addressed the underlying Context7 race risk by pre-pinning agent-framework version range now in design D5.

4. **New observability spec delta added.** trace_graph_call was specified in graph-client/spec.md as "a new method on the observability provider, registered in this change" but never actually MODIFIED the ObservabilityProvider Protocol anywhere. New specs/observability/spec.md delta adds the method to the Protocol with NoopProvider, LangfuseProvider, and resilience-composition scenarios. proposal.md Impact updated to list observability as affected.

5. **Path bug fix in work-packages.yaml.** wp-foundation listed src/assistant/core/observability.py in write_allow plus locks but that path does not exist. The actual provider modules live at src/assistant/telemetry/providers/{base,noop,langfuse}.py. Fixed all three occurrences plus the lock key plus the lock reason text. This was missed by all five Explore agents and would have blocked implementation.

6. **Security hardening: HTTP client lifecycle plus cross-domain redirect rejection.** Two new graph-client spec requirements. async-with semantics on GraphClient ensure deterministic httpx.AsyncClient closure pre-P10. follow_redirects=False plus trusted_hosts validation on @odata.nextLink prevents bearer-token leak via attacker-controlled redirect.

7. **Resilience-edge tightening.** 429 Retry-After spec gained two scenarios for past HTTP-date and malformed values. Both fall through to default backoff with sanitized warning rather than raising or hanging.

8. **Pagination discipline as a normative requirement.** N+1 patterns on Graph trip throttling for the entire tenant, not just the calling persona. New ms-extensions requirement prohibits per-item Graph fetches inside list-tools, mandates expand or select for enrichment, requires bounded API call count documented in tool docstrings. Per-tool page_ceiling override is now spec'd.

9. **Testability: vague event-loop-responsive criterion replaced with measurable timeouts.** msal-auth concurrent-calls scenario now specifies 100 ms mocked MSAL block plus 250 ms total wall-clock bound for two concurrent calls plus 10 ms yield bound on unrelated asyncio.sleep zero, all verifiable via asyncio.wait_for.

10. **MSAF MemoryPolicy follow-up scope explicitly documented.** The minimal-prepend approach is acknowledged as a deliberate trade-off pending an agent-framework SDK memory hook, with revisit criteria stated.

11. **wp-foundation loc_estimate bumped from 1900 to 3000.** The round-1 remediation added 38 section-8 tasks expanding foundation scope by ~1100 LOC; the existing comment noted growth but the number was stale. PLAN_ITERATE iteration 1 added another section-9 with about 15 tasks adding maybe 200 more LOC. New loc_estimate reflects post-round-1 reality with a small headroom for iteration-1 additions.

### Alternatives Considered

- **Consolidate all pyproject deps into wp-foundation per the feasibility agent's option A**: rejected because agent-framework is semantically a harness concern not a foundation concern, and the dep edge already prevents lock contention. Pre-pinning the version range in design D5 addresses the underlying risk without breaking package boundaries.
- **Add an observability rate-limiter or scope-coverage validator as new design elements**: deferred to P5b follow-up issues. Both raised by the security agent but introduce new design surface that should not be sneaked in via PLAN_ITERATE. They will be filed as GitHub issues at SUBMIT_PR time.
- **Decompose wp-foundation into wp-foundation-base and wp-foundation-remediation**: rejected. The 38 section-8 tasks are all foundation-scoped (cloud_client, msal_auth, graph_client, persona, telemetry providers); decomposition would force a synthetic boundary for no parallelism gain since they all touch foundation files. loc_estimate bump captures the reality.

### Trade-offs

- Accepted writing more spec scenarios (about 18 new scenarios across 5 spec files) over deferring to test-implementation discovery. Specs are the contract; missing scenarios mean implementers guess.
- Accepted an additional new spec delta (observability) over inlining trace_graph_call into graph-client. Adding to graph-client would have hidden a Protocol modification that future readers would expect to find in observability.

### Open Questions

- [ ] Whether the trusted-host list for cross-domain redirect rejection should be runtime-extensible via persona config (for sovereign-cloud customers): deferred. Default list covers public Graph plus three documented sovereign endpoints. Persona override is in the constructor signature already.
- [ ] Whether the "remain responsive" measurable timing thresholds (100 ms / 250 ms / 10 ms) are robust on slow CI runners: medium concern. If flake observed at impl time, scale via constants (MSAL_MOCK_BLOCK_MS, ASYNC_SLEEP_TOLERANCE_MS) parameterized in the test fixture rather than tightening the spec.

### Context

This iteration was launched as the autopilot PLAN_ITERATE phase after a fresh /autopilot ms-graph-extension invocation found the proposal already had PLAN plus PLAN_REVIEW round 1 plus remediation completed externally. The five-agent parallel-Explore approach (each agent under 700 words, single-dimension focused) surfaced one new critical finding (work-packages.yaml stale path) that all single-pass approaches would likely have missed. Net change: 1 new spec delta (observability), 18 new spec scenarios across 5 files, 15 new tasks in a new section 9, two task allocations in work-packages.yaml, one design D5 amendment (version pin), two design D-section enhancements (D3 code example fix), one Impact section update in proposal.md. openspec validate --strict passes after the iteration. Next phase: PLAN_REVIEW round 2 dispatched via parallel-review-plan to verify remediation closes the iteration findings without introducing new ones.

---

## Phase: Plan Review Round 2 (2026-05-06)

**Agent**: claude_code Opus 4.7 1M (orchestrator) plus gemini-local plus codex-local (attempted) | **Session**: autopilot P5 PLAN_REVIEW phase

### Decisions

1. **Two-vendor convergence achieved despite codex unavailability.** Codex dispatch failed at all three model attempts (gpt-5.5, gpt-5.4, gpt-5.4-mini) with OpenAI capacity exhaustion. Gemini dispatch reported timeout-after-600s but actually succeeded — its findings file was written before the dispatcher's stdout collection timed out. Filed as a parallel-infrastructure follow-up: dispatcher should check findings-file existence after timeout before declaring failure. Net result: claude_code self-review plus gemini-local equal 2-vendor quorum met.

2. **16 distinct findings synthesized from round 2.** 1 critical, 2 high, 7 medium, 6 low. 12 fixed in iteration 2 commit aa03743. 3 rejected as already-addressed or over-cautious. 1 escalated to human (wp-foundation decomposition).

3. **Cross-vendor blind spots are real and complementary.** Gemini caught 4 high+critical issues that claude_code self-review missed: D3 get_bytes return type mismatch (annotated bytes vs spec dict), CloudGraphClient Protocol missing lifecycle method declarations, D10 versus D27 MemoryPolicy contradiction, multi-PCA-instance tmp-file race in token cache write path. Claude found issues gemini missed: https-only scheme requirement on @odata.nextLink, observability kwarg consistency between specs, page-size-independent pagination bound. Different blind spots is the value proposition of cross-vendor convergence.

4. **Round-1 vendor-knowledge contributions persist into round 2.** Codex unavailability in round 2 did not erase its round-1 contribution because the spec content seen by codex in round 1 is the basis from which round-2 review applies. The 5 highs codex contributed in round 1 (HTTP 202 empty bodies, Retry-After throttling, write idempotency hazards, factory signature mismatch) all stayed closed in round 2, confirming the remediation worked.

### Tooling Notes

- Codex v0.128.0 with the openai provider hit capacity-exhausted on three model attempts in approximately 12 seconds. Likely an OpenAI API tier or quota issue. The fallback chain (gpt-5.5 to gpt-5.4 to gpt-5.4-mini) implies the dispatcher tried each in turn and all failed. Worth investigating tier configuration on this account.
- Gemini-local with model auto succeeded at the actual review work but the dispatcher process management timed out at 600s. The findings file is unambiguous evidence of success (references trusted_hosts and observability spec.md and Cross-Domain Redirect Rejection from iteration 1). Filed as parallel-infrastructure issue: detect file-existence after timeout and reclassify outcome.

---

## Phase: Plan Iteration 3 (2026-05-06)

**Agent**: claude_code Opus 4.7 1M | **Session**: autopilot P5 PLAN_FIX (escalation resolution)

### Decisions

1. **Foundation work-package split into protocols + impls.** wp-foundation in iteration 2 had grown to ~3000 LOC and 54 tasks. Iteration 1 rejected decomposition; iteration 2 self-review re-raised it as the section-9 additions tipped the balance; user selected Option C (split now) over Option A (defer to P5b) and Option B (accept as-is). New design section D28 documents the split rationale. New design section D29 documents pyproject ownership consolidation in impls.

2. **wp-foundation-protocols** (~600 LOC, no deps) owns pure-interface code: `core/cloud_client.py` (CloudGraphClient Protocol with 5 transport plus 3 lifecycle methods), `core/persona.py` (extended factory contract), `telemetry/providers/base.py` (ObservabilityProvider Protocol modification adding trace_graph_call), `tests/mocks/graph_client.py` (typed MockGraphClient that satisfies the Protocol). Tasks 1.1, 1.2, 1.15, 8.4.x, 9.1.1, 9.1.2, 9.2.x. Lock TTL 60 minutes — short window because no httpx or MSAL or Langfuse code is touched.

3. **wp-foundation-impls** (~2400 LOC, depends on protocols) owns concrete code: `core/msal_auth.py` (MSALStrategy Protocol plus impls — co-located because the Protocol is narrowly scoped to MSAL and not reused by P14 Google extensions), `core/graph_client.py` (httpx GraphClient impl), `telemetry/providers/{noop,langfuse}.py`, plus pyproject.toml with all three external deps (msal, respx, agent-framework). Tasks 1.3-1.14, 1.16, 8.1.x, 9.1.3-9.1.9, 9.4.1.

4. **MockGraphClient placement: protocols, not impls.** Because its purpose is to satisfy CloudGraphClient without an httpx impl, putting it in impls would force every extension test suite to wait for impls to land. It is a typed test fixture, not a concrete network client.

5. **Pyproject ownership consolidates in impls.** Previously wp-msaf-harness owned the agent-framework dep; now impls owns all three deps. wp-msaf-harness declares `consumes_external_deps: [agent-framework]` and depends on impls so the dep is installed before harness implementation begins. Single pyproject lock window during the merge train.

6. **Extension packages now depend ONLY on protocols.** They use MockGraphClient in tests and import CloudGraphClient via typing. wp-msaf-harness depends on protocols plus impls. wp-integration depends on all priority-2 packages.

### Alternatives Considered

- **Keep monolithic foundation per Option B**: rejected because the parallelism win for the four extensions is concrete (critical-path drop from 3000 LOC to 600 LOC, approximately 5x reduction) and the split boundary is clean — Protocol files are intentionally type-only contracts.
- **Defer split to P5b per Option A**: rejected because the user explicitly chose Option C, and the split before implementation begins is significantly cheaper than after.
- **Move MSALStrategy Protocol to protocols package**: rejected because MSALStrategy is narrowly scoped to MSAL and not reused by P14 Google extensions which will use OAuth-flow shaped abstractions. Splitting a small Protocol from its only impls would create maintenance overhead with no reuse benefit.

### Trade-offs

- Accepted +1 work package (now 7 plus integration) and a 6th max_loc bucket bump (4200 to 5000) to gain the parallelism for extensions.
- Accepted slight maintenance overhead of two foundation packages (need to coordinate Protocol additions across both) over the simplicity of one foundation package, because the split boundary is well-defined and the parallelism is tangible.

### Open Questions

- [ ] Whether section 8.1.x and 9.1.x tasks still implicitly reference Protocol method additions (e.g., 9.1.2 says "Add trace_graph_call to base.py Protocol; implement in noop.py and langfuse.py"). Mechanically the Protocol-method addition lives in protocols package; the noop and langfuse impls live in impls package. The task description as written conflates both. For implementation cleanliness, an agent picking up 9.1.2 in protocols package would only update base.py; an agent in impls would update noop.py and langfuse.py. The task ID 9.1.2 is in protocols package — so the Protocol declaration goes there, with the impls handled separately by the agent picking up 9.1.2 implementation in impls. Note for implementer: when this pattern occurs, the task is split-by-package automatically and the implementer should only modify files in their write_allow scope.

### Context

User selected Option C (split now) at the autopilot escalation. Iteration 3 implemented the split: work-packages.yaml restructured (one package became two; max_loc bumped to 5000; max_packages bumped to 7); design.md gained two new D-sections (D28 split rationale, D29 pyproject consolidation); tasks.md header revised with new package allocation guide. openspec validate --strict passes. Round-3 PLAN_REVIEW skipped because the change is structural (no spec content changes; only DAG and ownership) and vendor-dispatch reliability is currently low. Convergence declared. Next phase: IMPLEMENT.
