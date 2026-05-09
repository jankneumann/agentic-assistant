# IMPL_REVIEW round 1 — ms-graph-extension (P5)

You are doing a multi-vendor implementation review of OpenSpec change `ms-graph-extension` on branch `openspec/ms-graph-extension`. This is round 1 of the IMPL_REVIEW phase, after IMPL_ITERATE iteration 2. Your output will feed a consensus synthesizer that compares findings across vendors.

## Scope

Review the full implementation diff `main..HEAD` (~13 commits, ~17k LOC across ~81 files). Particular focus areas:

1. **Foundation** (`src/assistant/core/cloud_client.py`, `src/assistant/core/msal_auth.py`, `src/assistant/core/graph_client.py`) — Protocol shape, MSAL auth, httpx transport with `@resilient_http` retry + per-source circuit breaker
2. **Four real M365 extensions** (`src/assistant/extensions/{ms_graph,outlook,teams,sharepoint}.py`) — replace P1 stubs; each emits LangChain `StructuredTool` AND MSAF `@ai_function` callables (D11 dual-format parity)
3. **MSAgentFrameworkHarness** (`src/assistant/harnesses/sdk/ms_agent_fw.py`) — replaces `NotImplementedError` stub with full SDK integration
4. **Spec compliance** — all SHALL/MUST clauses in `openspec/changes/ms-graph-extension/specs/**/*.md`

## Context to read first

- `openspec/changes/ms-graph-extension/proposal.md`
- `openspec/changes/ms-graph-extension/design.md` — decisions D1–D29 encode WHY each non-obvious choice was made
- `openspec/changes/ms-graph-extension/specs/` — seven spec deltas
- `openspec/changes/ms-graph-extension/work-packages.yaml` — 8 packages with file scopes
- Recent iterate commits `8ef26f3` and `d1e8d2a` for changes since first impl

## Output format — STRICT

Output ONLY valid JSON conforming to `openspec/schemas/review-findings.schema.json`. Required top-level shape:

```json
{
  "review_type": "implementation",
  "target": "ms-graph-extension",
  "reviewer_vendor": "<your-vendor-name>",
  "findings": [
    {
      "id": 1,
      "type": "spec_gap|contract_mismatch|architecture|security|performance|style|correctness|observability|compatibility|resilience",
      "criticality": "critical|high|medium|low",
      "description": "Concise problem statement with file:line reference",
      "resolution": "Concrete fix recommendation",
      "disposition": "fix|regenerate|accept|escalate",
      "package_id": "whole-branch"
    }
  ]
}
```

## Review dimensions — high priority

- **spec_gap**: SHALL/MUST clauses in spec deltas not satisfied by implementation
- **security**: token handling, TLS, redirect rejection, secret persistence, injection vectors
- **resilience**: retry idempotency (D18 — non-idempotent writes pass `retry_safe=False`), circuit breaker keying, timeout handling, retry-after caps
- **correctness**: incorrect Graph API endpoints, wrong query params, broken pagination, missing await
- **contract_mismatch**: D11 dual-format parity violations, factory contract D26 violations
- **observability**: missing `trace_graph_call` invocations, error context in catch blocks

## Review dimensions — lower priority

- style/naming
- doc-strings
- minor performance

## Rules

- **DO NOT modify any files.** Read-only review.
- **Output ONLY the JSON object.** No prose, no markdown fences.
- **`reviewer_vendor` MUST identify your model.**
- Findings already addressed by iterate commits `8ef26f3` and `d1e8d2a` should NOT be re-reported. The iterate-1 commit body lists them: outlook send_email signature, sharepoint args_schemas, factory client kwarg symmetry, MSAF lazy import error message, graph_client trace gap on auth-refresh, msal_auth cache persist non-fatal. The iterate-2 commit lists: GraphClient max_retry_after_seconds, msal_auth fsync, _full_url ".." rejection, device-code logger, validate_path_segment rename.
- Be specific — file:line references and design-decision IDs (D1–D29) when applicable.
