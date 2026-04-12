# agentic-assistant

Framework-agnostic agent harness for building long-running AI assistants
with multiple personas (execution boundaries), composable roles (behavioral
patterns), and pluggable harness backends (Deep Agents, MS Agent Framework,
Claude Code, Codex).

Public code, private persona configs: persona definitions (prompts, memory,
role overrides, credentials) live in separate private repos mounted as git
submodules, so you can version-control sensitive context without exposing
it in the public repo.

## Quick start

```bash
git clone https://github.com/jankneumann/agentic-assistant.git
cd agentic-assistant

# Mount the persona submodules you have access to
git submodule update --init personas/personal
# git submodule update --init personas/work   # requires private repo access

# Install deps
uv sync

# Discover what's available
uv run assistant --list-personas
uv run assistant -p personal --list-roles

# Start an interactive session
uv run assistant -p personal
```

## Architecture

```
          researcher  planner  chief_of_staff  writer  coder
work    │  W+R        W+P      W+CoS           W+W     W+C    (deferred)
personal│  P+R        P+P      P+CoS           P+W     P+C
```

- `roles/` — shared behavioral definitions (public)
- `personas/<name>/` — private config submodules (DB URLs, auth, tone, etc.)
- `src/assistant/core/` — harness-agnostic persona/role/composition library
- `src/assistant/harnesses/` — adapters (Deep Agents today, MS Agent Framework in P5)
- `src/assistant/extensions/` — generic extension stubs (real impls in P4/P5)

See `CLAUDE.md` for more conventions and `openspec/roadmap.md` for the
planned proposal sequence.

## Status

P1 (bootstrap vertical slice): ships the core library, Deep Agents harness,
CLI with REPL/role-switching/delegation, all 5 public roles, and the
`personal` persona. Later proposals add HTTP tools, per-persona databases,
and real Google/MS integrations.

## License

MIT — see `LICENSE`.
