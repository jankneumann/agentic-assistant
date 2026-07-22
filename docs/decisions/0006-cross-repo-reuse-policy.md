# ADR-0006: Cross-repo reuse policy — share contracts, data, and stateful services; duplicate stateless mechanism

## Status

ACCEPTED — decided 2026-07-16; policy stated in
`docs/architecture-analysis/2026-07-16-protocol-standards.md` Part C
and consequence D.8, filed as an ADR under the X3 `repo-hygiene` task
(`openspec/roadmap.md`, row X3).

## Date

2026-07-16

## Context

Three sibling repos share an owner and overlapping concerns:
`agentic-assistant` (this repo), `agentic-coding-tools` (skills,
gen-eval, cost-aware vendor routing), and `agentic-content-analyzer`
(ACA — content indexing service). Code generation has made *writing*
code nearly free; it has not made *divergence* free, so the reuse
question recurs at every seam.

The costs of the wrong sharing mode are already demonstrated in-repo.
Commit `a878fa3` ("feat(eval): adopt gen-eval for plumbing
verification") declared gen-eval as a `[tool.uv.sources]` **path
dependency** (`gen-eval = { path =
"../agentic-coding-tools/packages/gen-eval" }` in `pyproject.toml`).
Any standalone clone — exactly the GX10 new-machine setup roadmap v3
targets — could not lock or sync, because the sibling checkout does
not exist at that relative path. The 2026-07-07 architecture review
recorded this as finding H3; commit `4689165` removed the dependency,
and `evaluation/README.md` now documents gen-eval as a *consumer* of
this repo's descriptors and scenarios, invoked from its own project,
never a dependency of this package.

## Decision

**Share contracts, data, and stateful services. Freely duplicate
stateless mechanism. Avoid cross-repo library imports.**

- **Always share (drift here is a bug):**
  - *Stateful services* — ACA owns its index/database and stays one
    service, consumed as tools: OpenAPI `http_tools` discovery today
    (teacher role, P8 vault endpoints), MCP when ACA grows that
    surface. The P24 ToolSpec compiler makes OpenAPI-vs-MCP a
    non-decision.
  - *Schemas and vocabularies* — the model-catalog format (OpenRouter
    `/models` mirror), capability-tag vocabulary, pricing data, eval
    finding schemas: one source (or duplicated files plus a
    conformance test), consumed by both P19's router and
    `agentic-coding-tools`' cost-aware routing.
  - *Security-critical logic* — sanitization/redaction rules (P26
    reuses `telemetry/sanitize.py`); shared as data/rulesets, not as a
    library.
- **Freely duplicate:** routers, retry wrappers, adapters, glue. Port
  the *design decisions*, write the code fresh. Two divergent
  implementations are fine when two divergent answers are fine.
- **Avoid cross-repo library imports:** libraries are coupling without
  a service boundary — the gen-eval incident above is the standing
  evidence. Prefer a service or a schema; if a package must be shared,
  publish it or vendor it, never path-depend on a sibling checkout.

## Consequences

- Standalone clones lock and test cleanly (`uv sync`, `uv run pytest
  tests/`) with no sibling repos present — a prerequisite for the GX10
  node and for CI.
- P19 shares the catalog schema and pricing data with
  `agentic-coding-tools` but not its router code; ACA integration
  needs no migration when its transport changes.
- Duplicated mechanism can drift by design; the guard is conformance
  tests on the shared schemas, not shared implementations.
