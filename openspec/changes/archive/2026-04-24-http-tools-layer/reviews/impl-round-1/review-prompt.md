# Implementation Review — `http-tools-layer` (Round 1)

You are an independent implementation reviewer for OpenSpec change
`http-tools-layer`. All 5 work packages + 1 IMPL_ITERATE fix have
landed. Your job: read the **implementation** and produce
structured findings. Another vendor is reviewing in parallel; a
synthesizer will merge findings.

## Target: implementation diff

Branch: `openspec/http-tools-layer`. Read with:

```bash
git log --oneline main..HEAD
git diff main...HEAD --stat
```

## Key source files to review

**Core implementation**:
- `src/assistant/http_tools/__init__.py` — D8 minimal re-exports
- `src/assistant/http_tools/auth.py` — resolve_auth_header (D11)
- `src/assistant/http_tools/openapi.py` — parse_operations + $ref resolver (D10)
- `src/assistant/http_tools/registry.py` — HttpToolRegistry (D3, D7)
- `src/assistant/http_tools/builder.py` — _build_tool (D1, D2, D6, D9)
- `src/assistant/http_tools/discovery.py` — discover_tools orchestrator
- `src/assistant/core/capabilities/tools.py` — DefaultToolPolicy extension
- `src/assistant/core/capabilities/resolver.py` — CapabilityResolver wiring
- `src/assistant/core/persona.py` — auth_header schema evolution (D11)
- `src/assistant/cli.py` — discover_tools wiring + --list-tools flag

**Tests** (should cover every SHALL in specs/http-tools/spec.md):
- `tests/http_tools/test_auth.py` (6)
- `tests/http_tools/test_openapi.py` (11)
- `tests/http_tools/test_registry.py` (8)
- `tests/http_tools/test_builder.py` (12)
- `tests/http_tools/test_discovery.py` (11)
- `tests/core/capabilities/test_tool_policy_http.py` (6)
- `tests/core/test_persona_auth_header.py` (6)
- `tests/test_cli.py` (24 total, 8 new for P3)

**Contracts**:
- `openspec/changes/http-tools-layer/contracts/fixtures/*.json`

**Specs** (the contract under test):
- `openspec/changes/http-tools-layer/specs/http-tools/spec.md`
- `openspec/changes/http-tools-layer/specs/tool-policy/spec.md`
- `openspec/changes/http-tools-layer/specs/cli-interface/spec.md`
- `openspec/changes/http-tools-layer/design.md` (D1–D11 decisions)

## Review dimensions

1. **Correctness** — does the implementation match each spec
   scenario? Are there edge cases not covered? Note especially:
   - `_resolve_ref_recursive` — does it handle `$ref` nested in
     properties, arrays, nested arrays?
   - `_read_body_with_size_cap` — does it actually abort mid-stream
     on cap violation, or buffer first? (D9 streaming enforcement)
   - `_build_tool` — does the args_schema handle all JSON Schema
     cases? What if the body has `"required": []`? What about
     `"additionalProperties"`?
   - Path-param substitution — what if the same param appears twice
     in a path?
2. **Security** — D9 posture (timeout, no-redirect, 10 MiB cap, TLS
   verify, credential redaction) preserved end-to-end?
   - Are warning log messages free of auth-header values?
   - Any SSRF vector I missed (user-configured base_url reaching
     file:// or internal IPs)?
3. **Type safety / robustness** — unused type-ignores, missed
   edge cases in str/dict narrowing, what happens if OpenAPI has
   unexpected keys.
4. **Test quality** — does every test actually assert the spec
   scenario it claims? Are there mock-heavy tests that would pass
   even if the implementation were broken?
5. **API cleanliness** — D8 minimal exports honored? Any leaked
   internal names? Dead code (e.g. `_async_wrapper` is identity —
   intentional or dead?)
6. **Integration** — does the CLI wire through correctly? Does the
   shared `async with` client scope actually cover per-tool
   invocations when LLM uses them?
7. **OpenSpec compliance** — does the change pass `openspec
   validate --strict`? (It does locally — but do the spec
   scenarios match the actual behavior?)

## Output format

Return ONLY a JSON object on stdout — no markdown fences:

```json
{
  "findings": [
    {
      "id": 1,
      "type": "correctness | security | testability | type_safety | api | integration | openspec_compliance",
      "criticality": "critical | high | medium | low",
      "description": "Concrete, specific. Cite file:line when applicable.",
      "disposition": "fix | accept | escalate",
      "resolution": "Specific recommendation (1-3 sentences).",
      "file_path": "src/assistant/<file>",
      "line_start": null,
      "line_end": null
    }
  ]
}
```

## Rules

- Be specific. "Needs more tests" is not a finding; "test X does not
  assert the 10 MiB cap fires mid-stream, only at final join" is.
- Ground every finding in code you actually read.
- Honest criticality: critical = data leak / crash, high = broken
  scenario, medium = edge case, low = nit.
- Empty `findings: []` is a valid and expected result if the
  implementation is clean.
- Skip finding categories already addressed in the plan-review trail:
  - MB/MiB unit mismatch (fixed in plan iteration 3)
  - Auth schema evolution (D11 implementation is wp-prep)
  - Streaming enforcement design (fixed in plan iteration 3)

Return JSON on stdout. Nothing else.
