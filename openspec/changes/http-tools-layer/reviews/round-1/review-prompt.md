# Plan Review — `http-tools-layer` (Round 1)

You are a senior reviewer performing an independent critique of the **plan
artifacts** for OpenSpec change `http-tools-layer` before implementation
begins. Another vendor is reviewing in parallel; a synthesizer will merge
your findings. Focus on substance — do not rubber-stamp.

## Artifacts under review

Read these files from the change directory
`openspec/changes/http-tools-layer/`:

- `proposal.md` — Why / What Changes / Approach selected / Impact
- `design.md` — 8 design decisions (D1–D8)
- `tasks.md` — 11 phases, TDD-ordered
- `work-packages.yaml` — 5 packages with DAG, scopes, locks
- `specs/http-tools/spec.md` — ADDED requirements
- `specs/tool-policy/spec.md` — MODIFIED requirements
- `specs/cli-interface/spec.md` — MODIFIED + ADDED requirements
- `contracts/fixtures/*.json` — OpenAPI 3.0, 3.1, malformed, Swagger 2.0
- `session-log.md` — decisions + iteration 1 notes

## Background (for context, not review target)

- Phase P3 of `openspec/roadmap.yaml`. Adds `src/assistant/http_tools/`
  package that discovers tools via `{base_url}/openapi.json` (fallback
  `/help`) and exposes them as LangChain `StructuredTool` instances via
  the `ToolPolicy` protocol from the archived `capability-protocols`
  change (P1.8).
- Approach A was chosen: dedicated `http_tools/` module, registry
  injected into `CapabilityResolver`. No `ToolSource` abstraction
  (deferred to P17).
- Iteration 1 already addressed: `__init__.py` ownership (D8), Swagger
  2.0 skip-with-warning, explicit `caplog` verification guidance.

## Review dimensions

Evaluate across these dimensions. Skip any not applicable:

1. **Completeness** — missing scenarios, unaddressed requirements, gaps
   between spec and tasks. In particular: does every scenario in every
   spec file have a corresponding test task?
2. **Clarity** — ambiguous requirements, hand-wavy tasks, unclear
   behavior in edge cases (empty input, network timeout, invalid
   content-type, truncated response, oversized response).
3. **Feasibility** — is the work-packages DAG actually buildable in the
   order given? Are `write_allow` scopes non-overlapping? Is
   `max_loc: 1500` realistic for this change?
4. **Security** — auth credentials from env, error messages that could
   leak secrets, SSRF risk from user-configured `base_url`, TLS
   verification, request timeouts, response size limits, path-parameter
   injection.
5. **Testability** — can every scenario be tested as specified? Are the
   `pytest-httpserver` fixtures sufficient? Will `caplog` assertions
   actually catch the warning behavior?
6. **Architectural coherence** — does the plan fit the existing
   `ToolPolicy` / `CapabilityResolver` / `DefaultToolPolicy` seam cleanly?
   Any cyclic imports? Does D8 (minimal `__init__.py`) actually prevent
   the DAG race it claims to prevent?
7. **Parallelizability** — are the work packages truly parallelizable
   where claimed? Any hidden file contention beyond what `locks` declare?
8. **OpenSpec compliance** — do Requirement bodies lead with `SHALL` /
   `MUST`? Are scenarios in `- **WHEN** ... - **THEN** ...` form?

## Output format

Return ONLY a JSON object with a single top-level `findings` array.
Each finding MUST match this schema:

```json
{
  "id": 1,
  "type": "spec_gap | architecture | security | performance | testability | clarity | feasibility | openspec_compliance",
  "criticality": "critical | high | medium | low",
  "description": "Concrete, specific. Reference file:line when applicable.",
  "disposition": "fix | accept | escalate | regenerate",
  "resolution": "Specific recommendation (1-3 sentences).",
  "file_path": "openspec/changes/http-tools-layer/<file>",
  "line_start": null,
  "line_end": null
}
```

## Rules

- **Be specific.** "Needs more detail" is not a finding; "scenario X
  does not specify behavior when the OpenAPI document exceeds 10MB" is
  a finding.
- **Ground every finding in an artifact.** If you cannot cite a file
  (or an absence in a file), the finding is not actionable.
- **Prioritize correctly.** `critical` = will break the system or leak
  data. `high` = will cause significant rework. `medium` = clarity /
  small gap. `low` = nit / style. Do NOT over-inflate criticality.
- **No style nits unless egregious.** This is a plan review, not a
  lint pass.
- **Iteration 1 already fixed**: `__init__.py` ownership (D8), Swagger
  2.0 skip scenario + fixture + task, `caplog` verification. Do NOT
  re-raise these unless you find a deeper issue in the fix itself.
- If you find no blocking issues, return `{"findings": []}`. That is a
  valid and welcome result.

Return the JSON on stdout. Do not wrap in markdown code fences.
