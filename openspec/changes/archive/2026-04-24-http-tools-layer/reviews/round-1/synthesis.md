# Round 1 Plan Review — Consensus Summary

**Date**: 2026-04-24
**Vendors**: claude (primary), codex, gemini
**Raw findings**: 32 (claude 15 + codex 10 + gemini 7)

The ConsensusSynthesizer clustered 0 of 32 findings across vendors
because the string-similarity matcher is tuned for identical wording
and our three vendors described overlapping issues in different prose.
Manual clustering below identified 14 substantive issues; 10 were
addressed in iteration 2.

## Multi-vendor confirmed issues

| ID | Clusters vendors | Criticality | Disposition |
|----|------------------|-------------|-------------|
| C1 | claude + codex + gemini — OpenAPI `$ref` resolution unspecified | high | FIXED |
| C2 | claude (critical) + codex (high) — persona.py `auth_header_env` flat string vs. spec `{type, env, header?}` structured dict mismatch | critical | FIXED |
| C3 | claude + codex — `httpx.AsyncClient` lifecycle: `weakref.finalize` + `run_until_complete(aclose())` is broken; also cross-source leakage concern | high | FIXED (D2 rewritten to `async with`) |
| C4 | claude + gemini — no timeout, no response-size cap, no TLS-verify posture, no `follow_redirects=False` | high | FIXED (D9 added + security posture Requirement) |
| C6 | codex + gemini — exception handling inconsistency (auth raises but discovery swallows) | high/medium | FIXED (Scenario "Missing auth env var at discovery time") |

## Single-vendor medium+ issues addressed

| ID | Vendor | Criticality | Disposition |
|----|--------|-------------|-------------|
| C5 | codex | high | FIXED (proposal.md Why clarifies `allowed_tools` scope) |
| C7 | codex | medium | ACCEPTED — false positive: `wp-integration` is exempted by `complexity_gate._count_impl_packages`; only 5 impl packages + 1 integration; raised `max_packages` to 5 anyway for clarity |
| C8 | codex | medium | FIXED — tasks 1.1-1.4 reworded to "verify" not "write" (fixtures already present); new fixture files (1.6, 1.7) added to wp-leaves write_allow |
| C10 | claude | medium | FIXED — removed `tests/http_tools/test_cli_list_tools.py` from wp-cli scope; consolidated in `tests/test_cli.py` |
| C11 | gemini | medium | FIXED — new scenario "StructuredTool name matches registry key" |
| C12 | claude | medium | FIXED — new Requirement clause on credential redaction + scenario "Auth header value absent from logs" |
| C13 | claude | medium | FIXED — new scenarios "Non-JSON 2xx content-type raises" + "Empty-body 2xx returns None" |
| C14 | claude | medium | FIXED — Phase 0 installs pytest-httpserver before test phases run |

## Accepted (not addressed — low criticality / deferred)

| ID | Vendor | Criticality | Reason |
|----|--------|-------------|--------|
| — | gemini | low | Slug collision risk in operationId fallback — unlikely in practice; collision would surface at registry insertion |
| — | gemini | low | Fallback-trigger ambiguity (only 404 triggers `/help`) — spec already says "returns HTTP 404"; clarified implicitly via redirect refusal (3xx is skipped, not followed to /help) |
| — | claude | low | G5 lead-with-SHALL nit — `openspec validate --strict` already passes |
| — | codex | medium | Performance target for huge OpenAPI docs — explicitly deferred per D9 10MiB cap + no P3 perf target |
| — | codex | medium | Run-vs-`run` CLI subcommand scenarios in cli-interface — existing spec inherited from P1; out of P3 scope |
| — | gemini | low | Ambiguous per-source allowed_tools — clarified in proposal Why paragraph (no new behavior in P3) |

## Iteration 2 changes

### Spec additions
- New Requirement: **HTTP Client Security Posture** (timeouts, TLS,
  redirects, response-size cap, credential redaction in logs) with
  3 scenarios
- New scenarios on **OpenAPI Operation Parsing**: `$ref` intra-doc
  resolution, external-ref skip, cyclic-ref detection
- New scenarios on **Tool Builder**: non-JSON content-type, empty-body
  204, tool name equals registry key, path parameter URL-encoded,
  required/optional field handling
- New scenario on **HTTP Tool Discovery**: missing auth env var skipped
- `Auth Header Resolution` now explicitly accepts both structured dict
  and legacy flat string shapes
- `HttpToolRegistry.list_all` ordering tightened from "deterministic
  order" to "lexicographic by key"

### Design additions
- **D2** rewritten — `async with httpx.AsyncClient()` replaces
  `weakref.finalize` + `run_until_complete(aclose())` (which was
  broken)
- **D9** — HTTP client security posture (timeout, redirects, TLS,
  size cap, credential redaction)
- **D10** — OpenAPI `$ref` resolution (intra-doc resolved, external
  skipped with warning, cyclic detected)
- **D11** — Persona `auth_header` schema evolution with legacy
  backwards-compat

### Tasks additions
- New **Phase 0** — persona schema extension + dev deps (tasks 0.1-0.4)
- Tasks 1.1-1.4 reworded to "verify" (fixtures exist); 1.5 narrowed to
  3.x fixtures only
- New tasks 1.6 (cyclic-ref fixture), 1.7 (external-ref fixture)
- New tasks 3.3, 3.4, 3.5 ($ref tests + impl)
- New tasks 4.3, 4.4, 4.5 (content-type, tool name, JSON Schema field
  handling)
- New tasks 6.4, 6.5, 6.6 (security posture, missing-env, credential
  redaction)

### Work-package additions
- New `wp-prep` at priority 0 — persona schema + pytest-httpserver dep
- `wp-cli` write_allow narrowed (removed `tests/http_tools/test_cli_list_tools.py`)
- `wp-http-tools-leaves` write_allow expanded with the two new fixture
  files
- `defaults.auto_loop.max_loc` raised 1500 → 1800 to cover added scope;
  `max_packages` raised 4 → 5 to match the impl-package count

## Ready for round 2 review
