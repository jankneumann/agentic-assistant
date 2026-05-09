# IMPL_REVIEW round 2 — ms-graph-extension (P5)

You are doing a multi-vendor convergence review of OpenSpec change `ms-graph-extension`. This is round 2 after round 1 surfaced 8 verified findings that were addressed in commit `458764e`.

## Round 2 scope

Two questions to answer:

1. **Are the round-1 findings now addressed?** Verify each fix below holds:
   - **R1+R2** (`src/assistant/core/graph_client.py:_get_bytes_inner`): refactored to handle 401 invalid_token force-refresh AND one-hop 302/307 redirect with Authorization stripping. Should fix SharePoint downloads.
   - **R3** (`_post_no_retry`): now calls `breaker.record_success()` on success path.
   - **R4** (`src/assistant/extensions/teams.py:_post_chat_message`): parameter renamed `content` → `text`; body now `{"body": {"content": text}}` (no `contentType`).
   - **R5** (`src/assistant/harnesses/sdk/ms_agent_fw.py`): `_compose_instructions` now goes through `_resolve_context_provider().compose_system_prompt(...)`; constructor accepts `context_provider` kwarg.
   - **R6** (`_send_with_auth_retry`): now catches all `httpx` transport-error subclasses and maps to `GraphAPIError` with distinct error_codes.
   - **R7** (`src/assistant/core/resilience.py` + `graph_client.py`): added `current_retry_attempt: ContextVar[int]` set by `resilient_http` retry loop; transport methods read it for `trace_graph_call(retry_attempt=...)`.
   - **R8** (`src/assistant/extensions/ms_graph.py:create_extension`): added `client: CloudGraphClient | None = None` kwarg.

2. **Did the remediation introduce any new bugs?** The largest-risk new code is the `_get_bytes_inner` refactor. Pay special attention to:
   - Tempfile cleanup on each error path (auth-refresh failure, redirect-rejection, size_exceeded, other 4xx/5xx)
   - Header state across retry iterations (Authorization re-set on refresh, removed on redirect)
   - The `auth_refreshes` / `redirect_follows` counters (each gates exactly one branch firing)
   - Span emission on every path including the auth-refresh exception branch
   - `current_retry_attempt` ContextVar interaction with concurrent calls

## Scope

The full implementation diff `main..HEAD` (now 14 commits, ~17.5k LOC). Highest-priority files:

- `src/assistant/core/graph_client.py` (heavily modified in `458764e`)
- `src/assistant/core/resilience.py` (new ContextVar)
- `src/assistant/harnesses/sdk/ms_agent_fw.py` (ContextProvider wiring)
- `src/assistant/extensions/teams.py` + `ms_graph.py` (small fixes)

## Output format — STRICT (same as round 1)

Output ONLY a JSON object conforming to the round-1 shape:

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
      "description": "Concise file:line problem statement",
      "resolution": "Concrete fix recommendation",
      "disposition": "fix|regenerate|accept|escalate",
      "package_id": "whole-branch"
    }
  ]
}
```

## Convergence rules

- **If round-1 findings R1–R8 are all addressed AND no new findings above the medium threshold**: return an empty `findings` array OR only `disposition: "accept"` low-criticality observations. This signals convergence.
- **If a round-1 finding is NOT actually addressed**: report it again with the original criticality.
- **If the remediation introduced a new bug**: report it as a fresh finding.

## Rules

- DO NOT modify any files.
- Output ONLY the JSON object.
- `reviewer_vendor` MUST identify your model.
- Be specific — file:line references where possible.
