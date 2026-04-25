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
- `src/assistant/harnesses/` — adapters (Deep Agents today, MS Agent
  Framework lands in the `ms-graph-extension` phase)
- `src/assistant/extensions/` — generic extension stubs (real impls in
  the `ms-graph-extension` and `google-extensions` phases)

See `CLAUDE.md` for more conventions and `openspec/roadmap.md` for the
planned proposal sequence.

## Observability

Optional Langfuse-backed tracing for harness invocations, sub-agent
delegations, memory operations, and tool calls. Off by default; opt in
via the `[telemetry]` extra plus `LANGFUSE_*` env vars.

```bash
# Bring up a self-hosted Langfuse stack (postgres, clickhouse, redis,
# minio, langfuse-web on http://localhost:3100). Seeded org/project/keys
# via LANGFUSE_INIT_* — no UI signup needed.
docker compose -f docker-compose.langfuse.yml -p langfuse up -d

uv sync --extra telemetry
export LANGFUSE_ENABLED=true LANGFUSE_HOST=http://localhost:3100
export LANGFUSE_PUBLIC_KEY=DUMMY-pk-lf-dev-local
export LANGFUSE_SECRET_KEY=DUMMY-sk-lf-dev-local
uv run assistant -p personal
```

See `docs/observability.md` for the full quickstart, delivery-guarantee
tradeoffs, privacy notes, and Claude Code Stop hook wiring instructions.

## Status

`bootstrap-vertical-slice` (archived, 2026-04-12): ships the core
library, Deep Agents harness, CLI with REPL / role-switching /
delegation, all 5 public roles, and the `personal` persona. See
`openspec/roadmap.md` for the 18-phase sequence that builds on this
foundation — HTTP tools, per-persona databases, observability, A2A
server, Obsidian vault integration, and real Google / MS integrations.

## License

MIT — see `LICENSE`.
