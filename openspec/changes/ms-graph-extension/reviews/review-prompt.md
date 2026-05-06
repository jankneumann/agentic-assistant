# Review Prompt — ms-graph-extension (Plan Phase)

You are reviewing an OpenSpec change proposal for **P5 ms-graph-extension** of the agentic-assistant project. Your job is to identify spec gaps, contract mismatches, architectural concerns, security issues, performance issues, observability gaps, compatibility risks, resilience gaps, correctness issues, and style/convention violations.

## Read these artifacts (read-only):

All paths relative to repo root:

- `openspec/changes/ms-graph-extension/proposal.md` — what, why, three approaches with sub-approach A.2 selected
- `openspec/changes/ms-graph-extension/design.md` — 12 decisions (D1–D12), risks/trade-offs, migration plan
- `openspec/changes/ms-graph-extension/specs/msal-auth/spec.md` — MSAL strategy abstraction
- `openspec/changes/ms-graph-extension/specs/graph-client/spec.md` — CloudGraphClient Protocol + custom GraphClient impl
- `openspec/changes/ms-graph-extension/specs/ms-extensions/spec.md` — four real Microsoft 365 extensions
- `openspec/changes/ms-graph-extension/specs/ms-agent-framework-harness/spec.md` — full MSAF harness implementation
- `openspec/changes/ms-graph-extension/specs/extension-registry/spec.md` — MODIFIED: narrow stub set to gmail/gcal/gdrive
- `openspec/changes/ms-graph-extension/specs/harness-adapter/spec.md` — REMOVED stub-state requirement, MODIFIED observability scenarios
- `openspec/changes/ms-graph-extension/tasks.md` — TDD-ordered task list with spec scenario references
- `openspec/changes/ms-graph-extension/contracts/README.md` — contract sub-types ruled out
- `openspec/changes/ms-graph-extension/work-packages.yaml` — six impl packages + integration

## Project context:

- Python 3.12, async-first, type-hinted, ruff + mypy + pytest
- Persona-based architecture (per-persona auth boundary)
- Functional prereqs P3 http-tools-layer, P1.8 capability-protocols, P9 error-resilience all archived
- Existing reusable modules: `core/resilience.py` (retry + circuit breaker), `http_tools/auth.py`, `core/persona.py` (`_env()` env-var lookup pattern)
- Existing harnesses: `harnesses/sdk/deep_agents.py` (reference SdkHarnessAdapter implementation)

## Discovery decisions (already locked, do NOT re-litigate):

- MSAL flow: interactive+silent + client_credentials, both pluggable. Web-interactive only (no msal[broker]).
- MSAF SDK: `agent-framework` (PyPI). Confirmed via Context7.
- API surface: read-heavy + send Outlook email + post Teams chat. SharePoint write-side, calendar create, Teams meeting create deferred.
- Test strategy: respx + typed MockGraphClient + opt-in `RUN_GRAPH_TESTS=1`.
- Persona default: personal persona stays opted out.
- Approach: A.2 (Transport-interface Protocol with custom MS impl).

## What to evaluate:

### Specification Completeness
- Do all requirements use SHALL/MUST language?
- Are requirements testable and unambiguous?
- Is anything missing that should be normative?

### Architecture Alignment
- Does the design follow existing project patterns (resilience integration, _env() lookups, persona-as-boundary)?
- Are abstractions justified?
- Are there leaky abstractions or hidden coupling?

### Security
- Token cache file discipline (mode 0o600, atomic write, gitignore)
- Authentication failure handling (no retry, sanitized errors)
- Any secrets in configuration paths?
- OWASP top-10 considerations for new HTTP code paths?

### Performance
- Any unbounded loops or queries (pagination ceiling matters)?
- Async correctness in MSAL strategy + GraphClient + extensions
- Caching strategy for tokens

### Observability
- New code paths emit observability spans?
- Existing observability requirements (trace_tool_call, trace_llm_call) preserved?
- Transport-level observability for Graph HTTP calls?

### Compatibility
- Breaking changes to extension-registry / harness-adapter — handled cleanly via deltas?
- Are migration paths reversible?

### Resilience
- Retry / timeout / fallback for Graph calls?
- 429 (rate-limit) handling and Retry-After respect?
- 401 (auth-expired) handling?
- Circuit breaker behavior at boundary?
- Idempotency for write tools (send_email, post_chat_message)?

### Work Package Validity
- DAG acyclic?
- Parallel write_allow scopes non-overlapping?
- Lock keys canonical?
- Verification tiers appropriate?

## Output format

Output **only** valid JSON conforming to `openspec/schemas/review-findings.schema.json`. Schema:

```json
{
  "review_type": "plan",
  "target": "ms-graph-extension",
  "reviewer_vendor": "<your vendor name e.g. codex or gemini>",
  "findings": [
    {
      "id": 1,
      "type": "spec_gap | contract_mismatch | architecture | security | performance | style | correctness | observability | compatibility | resilience",
      "criticality": "low | medium | high | critical",
      "description": "what the issue is, specific and actionable",
      "resolution": "what to do about it",
      "disposition": "fix | regenerate | accept | escalate",
      "file_path": "openspec/changes/ms-graph-extension/<path>"
    }
  ]
}
```

## Review style

- Be specific: cite file paths, requirement names, scenario names.
- Be honest: do not rubber-stamp. The plan was authored by another LLM and may have blind spots in vendor-specific knowledge (Entra ID, Microsoft Graph, the agent-framework SDK).
- Prioritize: HIGH/CRITICAL only for issues that should block implementation.
- Identify positives implicitly via absence — only emit findings, not praise.
- If you find no issues in a category, emit no findings for it.

Output the JSON object only. No markdown, no commentary, no preamble.
