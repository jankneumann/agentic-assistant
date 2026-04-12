# agentic-assistant — OpenSpec Roadmap

Derived from `agentic-assistant-bootstrap-v4.1.md`. The bootstrap spec is split
into sequenced OpenSpec proposals so each change is independently reviewable,
implementable, and validatable. One proposal per session to preserve context
and let implementation feedback inform later designs.

## Proposal sequence

| # | Change ID | Status | Description |
|---|-----------|--------|-------------|
| P1 | `bootstrap-vertical-slice` | in progress | Core library (persona, role, composition) + Deep Agents harness + CLI + 5 public roles + personal persona populated + extension stubs + delegation spawner + tests + CI |
| P2 | `http-tools-layer` | pending | `src/assistant/core/http_tools/` — `/help`-based discovery, StructuredTool builder, auth header handling, registry, `--list-tools` CLI command, integration tests against a mock server |
| P3 | `persona-db-layer` | pending | Per-persona `AsyncEngine`, schema init (`memory`, `preferences`, `interactions` tables), memory CRUD, Graphiti client factory, isolation tests |
| P4 | `google-extensions` | pending | Real `gmail`, `gcal`, `gdrive` extension implementations. LangChain StructuredTools + MS Agent Framework AIFunctions. OAuth refresh flow. |
| P5 | `ms-graph-extensions` | pending | Real `ms_graph`, `teams`, `sharepoint`, `outlook` extensions + MS Agent Framework harness (full impl, replacing the P1 stub) |
| P6 | `work-persona-config` | pending | (Deferred until work machine) Create `assistant-config-work` submodule, wire into `.gitmodules`, populate work persona config + role overrides |
| P7 | `cli-harness-integrations` | pending | Deeper Claude Code/Codex/Gemini integrations — slash commands in `.claude/commands/`, `.codex/skills/`, `.gemini/settings.json`, persona-aware routing |
| P8 | `advanced-delegation` | pending | `delegate_parallel`, monitoring/cancellation, delegation analytics tables, harness auto-routing by task type |
| P9 | `mcp-server-exposure` | pending | Expose the assistant as an MCP server so other Claude Code sessions can invoke it as a tool |
| P10 | `railway-deployment` | pending | Run persona instances as Railway services + deployment manifests |

## Dependency graph

```
P1 (bootstrap-vertical-slice)
 ├─→ P2 (http-tools-layer)
 ├─→ P3 (persona-db-layer)
 │    └─→ P8 (advanced-delegation)
 ├─→ P4 (google-extensions)  ──┐
 ├─→ P5 (ms-graph-extensions) ─┴─→ P9 (mcp-server-exposure)
 ├─→ P6 (work-persona-config) [independent, triggered by machine availability]
 └─→ P7 (cli-harness-integrations)
           └─→ P10 (railway-deployment)
```

## Out of scope for all proposals in this roadmap

From bootstrap spec Phase 16 — will be planned only if/when priorities shift:
cross-persona bridge, A2A protocol, multi-model routing, proactive monitoring,
NotebookLM integration, role learning, persona config encryption.
