# Tasks: repo-hygiene (X3)

## 1. Dependency portability

- [x] 1.1 Remove `gen-eval[mcp]` dependency + `[tool.uv.sources]` entry;
      document external gen-eval invocation in `evaluation/README.md`
- [x] 1.2 `agent-framework-core` pin (verify import surface; keep meta
      package with recorded blocker if core lacks the chat clients)
- [x] 1.3 `uv lock` + `uv sync` succeed standalone; quality gates green
      (`uv run pytest tests/`, `uv run ruff check src tests`,
      `uv run mypy src tests`)

## 2. Documentation debt

- [x] 2.1 Backfill `## Purpose` in all capability specs (24 on disk)
- [x] 2.2 Seed `docs/decisions/` with six retroactive ADRs

## 3. Wrap-up

- [ ] 3.1 Update roadmap row X3 + workspace checkpoint; archive change
