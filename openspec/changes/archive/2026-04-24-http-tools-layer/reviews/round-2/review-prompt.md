# Plan Review — `http-tools-layer` (Round 2)

You are a senior reviewer performing an independent critique of the
**plan artifacts** for OpenSpec change `http-tools-layer`. This is
Round 2; Round 1 produced 32 raw findings across 3 vendors, of which
10 were addressed in iteration 2.

## Round 1 → iteration 2 changes

Before reviewing, read
`openspec/changes/http-tools-layer/reviews/round-1/synthesis.md`
for the full accounting of what was addressed and what was accepted.
Key changes this round:

- **D2 rewritten**: `async with httpx.AsyncClient(...)` replaces the
  broken `weakref.finalize` + `run_until_complete(aclose())` pattern.
- **D9 added**: HTTP client security posture (timeout, TLS, 10 MiB
  cap, `follow_redirects=False`, credential redaction in logs).
- **D10 added**: OpenAPI `$ref` resolution — intra-document resolved,
  external skipped with warning, cyclic detected.
- **D11 added**: persona `auth_header` schema evolution with
  legacy-flat-string backwards compat.
- **New Phase 0**: persona schema extension + `pytest-httpserver`
  dev-dep installed BEFORE Phase 6/8 tests that depend on them.
- **New work-package `wp-prep`** at priority 0; all other packages
  depend on it.
- **New scenarios** in `specs/http-tools/spec.md`: missing-env skip,
  non-JSON content-type, empty 204, tool name, path URL-encoding,
  `list_all` key order, redirect refused, oversized response, auth
  value redaction.
- **New fixtures**: `cyclic_ref_openapi.json`,
  `external_ref_openapi.json`.
- **`wp-cli` scope narrowed**: removed ambiguous
  `tests/http_tools/test_cli_list_tools.py`.

## Scope of this round

**Confirm convergence** or surface NEW issues. Specifically:

1. **Regression check** — did any iteration-2 edit introduce a new
   bug, inconsistency, or dead reference? Look especially at:
   - Does `design.md` D9 match the posture enumerated in
     `specs/http-tools/spec.md` (the "HTTP Client Security Posture"
     Requirement)?
   - Does `tasks.md` Phase 0 produce the exact shape that `design.md`
     D11 describes, and do the new tasks 3.3/3.4/3.5/4.3/4.4/4.5/
     6.4/6.5/6.6 each map to a named spec scenario?
   - `work-packages.yaml` `wp-prep` dependencies + scope — are they
     actually non-overlapping with other packages?
2. **Did iteration-2 leave any round-1 finding unaddressed that
   should have been?** The synthesis enumerates which were accepted —
   challenge any that should not have been.
3. **Gate-to-IMPLEMENT readiness** — is the plan ready for
   implementation? If you would block IMPLEMENT on one item, name it.

## Artifacts under review

Read from `openspec/changes/http-tools-layer/`:
- `proposal.md`, `design.md`, `tasks.md`, `work-packages.yaml`
- `specs/http-tools/spec.md`, `specs/tool-policy/spec.md`,
  `specs/cli-interface/spec.md`
- `contracts/fixtures/*.json`
- `session-log.md` (round-1 entry + round-1 iteration-2 entry)
- `reviews/round-1/synthesis.md`

## Output format

Same schema as Round 1: JSON with a single `findings` array. Each
finding has: `id, type, criticality, description, disposition (fix/
accept/escalate/regenerate), resolution, file_path, line_start,
line_end`.

**Rules**:
- Empty `{"findings": []}` is a valid, expected result if
  iteration 2 truly addressed everything.
- Do NOT re-raise round-1 findings that `synthesis.md` lists as
  FIXED unless you find a deeper issue in the fix itself.
- Do NOT re-raise accepted items; `synthesis.md` explains why.
- NEW findings welcome (regressions from iteration 2 edits, things
  vendors missed in round 1).

Return JSON on stdout, no markdown fences.
