# Proposal: repo-hygiene (X3)

## Why

Roadmap v3 (arch-review §4, findings H1–H5) identified hygiene debt that
blocks clean execution of the remaining phases: all 25 capability specs
carry `## Purpose: TBD` placeholders; no ADRs exist although repo skills
reference `docs/decisions/`; the `gen-eval` path dependency
(`[tool.uv.sources]` → `../agentic-coding-tools/...`) breaks `uv sync`
and `uv lock` on any standalone clone — including this remote session
and the future GX10 node; and the `agent-framework` meta-package
namespace quirk is documented but unexecuted.

## What Changes

1. **Dependency portability**: remove `gen-eval[mcp]` from
   `[project.dependencies]` and its `[tool.uv.sources]` path entry.
   gen-eval is a consumer of this repo (descriptors/scenarios under
   `evaluation/`), not a library this package imports — no `import
   gen_eval` exists in `src/` or `tests/`. Evaluation runs invoke the
   gen-eval CLI from the tools repo where available; documented in
   `evaluation/README.md`.
2. **`agent-framework-core` pin**: replace the `agent-framework` meta
   package with `agent-framework-core` per the CLAUDE.md gotcha, if the
   core package provides the imported names (`OpenAIChatClient`,
   `AzureOpenAIChatClient`); otherwise keep the meta package and record
   the blocker.
3. **Spec Purpose backfill**: replace the TBD placeholder in all 25
   `openspec/specs/*/spec.md` files with a one-paragraph Purpose derived
   from each spec's requirements and originating change.
4. **ADR seed**: create `docs/decisions/` with retroactive ADRs for the
   load-bearing decisions: SDK/Host harness split, capability
   protocols, AG-UI adoption, test privacy boundary, model-seam choice
   (ModelProvider → ModelRef → bindings), cross-repo reuse policy.

## Impact

- Non-phase change (tooling/docs; no requirement deltas — Purpose text
  is not a requirement, so this change intentionally carries no
  `specs/` delta directory and is not validated with
  `openspec validate --strict`).
- Affected: `pyproject.toml`, `uv.lock`, `evaluation/README.md` (new),
  25 spec files, `docs/decisions/` (new), roadmap row X3.
- Risk: dependency re-lock could shift transitive versions — quality
  gates (pytest/ruff/mypy) must pass before archive.
