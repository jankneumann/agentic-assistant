# agentic-assistant-bootstrap-v4.1 — Review & Improvement Plan

> **Context**: This document is a structured review of `agentic-assistant-bootstrap-v4.1.md` with actionable improvements. Each section includes the problem, the recommended fix, and where applicable, implementation guidance. Use this to update the spec and implement the missing pieces.

---

## 1. Structural Gaps

### 1.1 No Observability Layer

**Problem**: The spec has no tracing, logging, or metrics for agent execution. For a multi-harness, multi-role system with sub-agent delegation, this makes debugging delegation chains and understanding cost per persona/role impossible.

**Recommendation**: Add `src/assistant/core/observability.py` that wraps agent invocations with structured tracing.

**Implementation guidance**:
- Use [Langfuse](https://langfuse.com/) (open-source, self-hostable) or [OpenLLMetry/Traceloop](https://github.com/traceloop/openllmetry) (OTel-native) — both avoid vendor lock-in.
- Every `harness.invoke()` and `spawner.delegate()` call should emit spans with:
  - `persona`, `role`, `harness`
  - Token usage (input/output)
  - Latency
  - Tool calls made
  - Delegation chain (parent → child roles)
- Add a `@traced` decorator or context manager that harness adapters and the delegation spawner use.
- Include cost tracking per persona/role for budget visibility.

**Where it goes**:
```
src/assistant/core/
├── observability.py       # Tracing, metrics, cost tracking
```

Add to `HarnessAdapter.invoke()` and `DelegationSpawner.delegate()`.

---

### 1.2 Memory Architecture is Split-Brained

**Problem**: Three memory systems exist that don't know about each other:
1. `memory.md` — flat file, version-controlled in private config repos
2. Postgres `memory` table — DB-backed key-value store
3. Graphiti — knowledge graph

The spec doesn't define which system of record wins for what, or how they sync. The `memory.py` module is referenced in the directory structure but never defined.

**Recommendation**: Define a clear hierarchy:

| System | Purpose | Reads | Writes |
|--------|---------|-------|--------|
| **Graphiti** | Long-term semantic memory — entities, relationships, temporal facts | Agent queries via search | Agent writes after interactions |
| **Postgres `memory` table** | Operational state — active projects, preferences, session context, routing decisions | Agent reads at session start | Agent writes during session |
| **`memory.md`** | Human-readable snapshot for version control and diffability | Humans review; harnesses (Claude Code, Codex) read as context | Auto-generated from Graphiti + Postgres via commit hook or scheduled export — NOT a primary write target |

**Implementation guidance**:
- Implement `src/assistant/core/memory.py` with a `MemoryManager` class that:
  - Reads from Postgres for operational state
  - Queries Graphiti for semantic context
  - Exposes a unified `get_context(persona, role)` method that merges both
  - Provides `store_preference()`, `store_fact()`, `store_interaction()` methods that route to the appropriate backend
- Add a `scripts/export-memory.sh` or a Python CLI command that dumps current Postgres + Graphiti state into `memory.md` format for committing to the private config repo.
- Clarify in the spec that `memory.md` is a derived artifact, not a source of truth.

---

### 1.3 No Error Recovery / Retry Strategy

**Problem**: `discover_tools()` swallows HTTP failures with a print statement. `DelegationSpawner.delegate()` has no retry or fallback. For a system orchestrating multiple HTTP backends and external APIs, this will cause silent failures.

**Recommendation**: Add a resilience layer.

**Implementation guidance**:
- Create `src/assistant/core/resilience.py` with:
  - Retry with exponential backoff for HTTP tool calls (use `tenacity` or hand-roll with `asyncio`)
  - Circuit breaker pattern for backend services (content-analyzer, coding-tools) — after N consecutive failures, stop calling for a cooldown period
  - Graceful degradation: when a backend is down, the agent should note it was unavailable in its output rather than silently omitting data
- Apply to:
  - `http_tools/client.py` — all outbound HTTP calls
  - `discover_tools()` — should retry on transient errors, hard-fail with clear message on persistent ones
  - Extension `health_check()` — should be called at startup and periodically, with unhealthy extensions disabled gracefully

**Dependencies to add**:
```
uv add tenacity
```

---

## 2. Chief of Staff Role Gaps

### 2.1 No Scheduling / Proactive Execution

**Problem**: The Chief of Staff role is reactive only — it waits for user input. The AI Chief of Staff blueprint (created April 2026) defined proactive capabilities: morning briefings, email triage on arrival, pre-meeting briefs. The spec has no scheduler.

**Recommendation**: Add `src/assistant/core/scheduler.py` supporting cron-like triggers.

**Implementation guidance**:
- Even if the initial implementation is a simple `asyncio` loop polling on schedule, the abstraction should exist.
- Add a `schedules` section to `persona.yaml`:

```yaml
# In persona.yaml (private config)
schedules:
  morning_briefing:
    cron: "0 7 * * 1-5"    # Weekdays at 7 AM
    role: chief_of_staff
    skill: briefing
    output: teams_chat       # Where to deliver the result
  email_triage:
    trigger: polling
    interval_minutes: 15
    role: chief_of_staff
    skill: triage
  pre_meeting_brief:
    trigger: calendar_event
    minutes_before: 60
    role: chief_of_staff
    skill: briefing
```

- The scheduler should:
  - Load schedule configs from the active persona
  - Create the appropriate harness + role for each scheduled task
  - Execute the skill workflow
  - Route output to the configured destination (Teams chat, file, etc.)
- Use `croniter` for cron expression parsing.

**Dependencies to add**:
```
uv add croniter
```

**Where it goes**:
```
src/assistant/core/
├── scheduler.py           # Cron and event-driven task scheduling
```

Add a `--daemon` flag to the CLI that starts the scheduler alongside the REPL.

---

### 2.2 Obsidian Vault Integration is Missing

**Problem**: The AI Chief of Staff blueprint's most differentiated component — RAG over the Obsidian vault synced via OneDrive — has no representation in v4.1. The content-analyzer backend is the natural home, but the spec should at minimum define the integration point.

**Recommendation**: Add an `obsidian` tool source or extension.

**Implementation guidance**:
- **Option A (preferred)**: Add Obsidian indexing to `agentic-content-analyzer` as a new endpoint, then reference it as a tool source in the work persona config. The content-analyzer already handles knowledge management — Obsidian vault is just another knowledge source.
- **Option B**: Add a standalone `src/assistant/extensions/obsidian.py` that:
  - Watches a configured directory (OneDrive-synced vault path)
  - Parses markdown files, handling Obsidian-specific syntax (wikilinks `[[]]`, frontmatter YAML, tags)
  - Indexes into Graphiti or a vector store (Postgres pgvector via ParadeDB)
  - Exposes search tools: `obsidian_search(query)`, `obsidian_get_note(path)`, `obsidian_recent_notes(days)`

**Persona config addition**:
```yaml
# In work persona.yaml
tool_sources:
  obsidian_vault:
    base_url_env: CONTENT_ANALYZER_URL
    auth_header_env: CONTENT_ANALYZER_AUTH
    allowed_tools:
      - obsidian_search
      - obsidian_get_note
      - obsidian_recent_daily_notes

# Or as an extension
extensions:
  - name: obsidian
    module: obsidian
    config:
      vault_path_env: WORK_OBSIDIAN_VAULT_PATH
      index_backend: graphiti  # or pgvector
      watch: true
      ignore_patterns:
        - ".obsidian/*"
        - ".trash/*"
```

---

## 3. Architecture Refinements

### 3.1 Extension Protocol Needs Lifecycle Hooks

**Problem**: The `Extension` protocol only has `health_check()`. Real extensions — especially MS Graph — need OAuth token refresh, connection pool management, and clean shutdown.

**Recommendation**: Extend the protocol in `src/assistant/extensions/base.py`:

```python
@runtime_checkable
class Extension(Protocol):
    name: str

    async def initialize(self) -> None:
        """Called once at startup — establish connections, refresh tokens."""
        ...

    async def shutdown(self) -> None:
        """Called on graceful shutdown — close connections, flush buffers."""
        ...

    async def refresh_credentials(self) -> None:
        """Called periodically or on 401 — refresh OAuth tokens, rotate keys."""
        ...

    async def health_check(self) -> bool:
        """Called at startup and periodically — return False to disable."""
        ...

    def as_langchain_tools(self) -> list[Any]: ...
    def as_ms_agent_tools(self) -> list[Any]: ...
```

**Update `PersonaRegistry.load_extensions()`** to call `initialize()` on each extension after creation, and register a shutdown handler.

---

### 3.2 Harness Selection Should Be Dynamic

**Problem**: Harness selection is a static CLI flag. In practice, certain tasks map better to certain harnesses — MS Agent Framework for M365 API calls, Deep Agents for complex multi-step reasoning. The `harness_routing` item in Phase 16 "Future Iterations" should not be deferred.

**Recommendation**: Add an `auto` mode to the harness factory.

**Implementation guidance**:
- In `src/assistant/harnesses/factory.py`, add routing logic:

```python
def select_harness(
    persona: PersonaConfig, role: RoleConfig, task_hint: str | None = None,
) -> str:
    """Auto-select the best harness for the given context."""
    enabled = [
        name for name, cfg in persona.harnesses.items()
        if cfg.get("enabled", False)
    ]

    if len(enabled) == 1:
        return enabled[0]

    # If role's preferred tools include MS Graph/Teams/Outlook,
    # prefer ms_agent_framework when available
    ms_tools = {"ms_graph:", "teams:", "sharepoint:", "outlook:"}
    if any(
        any(t.startswith(prefix) for prefix in ms_tools)
        for t in role.preferred_tools
    ) and "ms_agent_framework" in enabled:
        return "ms_agent_framework"

    # Default to deep_agents for complex reasoning
    return "deep_agents" if "deep_agents" in enabled else enabled[0]
```

- Update the CLI to default to `--harness auto` instead of `--harness deep_agents`.

---

### 3.3 Sub-Agent Context Loss

**Problem**: `DelegationSpawner.delegate()` passes only the task string to sub-agents. The sub-agent has no conversation history, memory context, or delegation chain awareness.

**Recommendation**: Add a `DelegationContext` dataclass.

**Implementation guidance**:
```python
@dataclass
class DelegationContext:
    parent_role: str
    delegation_chain: list[str]  # ["chief_of_staff", "researcher"] — for cycle detection
    memory_snippets: list[str]   # Relevant memory entries for the task
    conversation_summary: str    # Brief summary of parent conversation
    constraints: dict[str, Any]  # Inherited constraints (e.g., output format, audience)
```

- `DelegationSpawner.delegate()` should build a `DelegationContext`, serialize it, and prepend it to the task prompt sent to the sub-agent.
- Add cycle detection: if `sub_role_name` is already in `delegation_chain`, refuse to delegate (prevents infinite researcher → writer → researcher loops).

---

## 4. Security Improvements

### 4.1 Credential Isolation Isn't Complete

**Problem**: All personas share the same process and environment. Nothing prevents `PersonaConfig.load("personal")` from reading `WORK_MS_CLIENT_SECRET` from `os.environ`. The `_env()` helper blindly reads any env var.

**Recommendation**: Scope env var resolution per persona.

**Implementation guidance**:
- In `persona.py`, the `_env()` helper should validate that the requested env var name starts with the persona's expected prefix:

```python
def _env(var_name: str, persona_name: str = "") -> str:
    if not var_name:
        return ""
    # Optional: enforce prefix convention
    expected_prefixes = {
        "work": ["WORK_", "CONTENT_ANALYZER_", "CODING_TOOLS_", "ANTHROPIC_"],
        "personal": ["PERSONAL_", "CONTENT_ANALYZER_", "CODING_TOOLS_", "ANTHROPIC_"],
    }
    if persona_name and persona_name in expected_prefixes:
        if not any(var_name.startswith(p) for p in expected_prefixes[persona_name]):
            raise ValueError(
                f"Persona '{persona_name}' cannot access env var '{var_name}'. "
                f"Expected prefixes: {expected_prefixes[persona_name]}"
            )
    return os.environ.get(var_name, "")
```

- Alternatively, load persona-specific `.env` files: `personas/work/.env` and `personas/personal/.env`, loaded only when that persona is active.

---

### 4.2 Extension Code Execution Risk

**Problem**: `load_extensions()` executes `spec.loader.exec_module(mod)` on arbitrary Python files from the private config repo. Necessary but risky.

**Recommendation**: Add manifest validation.

**Implementation guidance**:
- Require a `manifest.yaml` in each private config repo's `extensions/` directory:

```yaml
# personas/work/extensions/manifest.yaml
extensions:
  - file: comcast_internal_api.py
    sha256: abc123...
    description: "Internal API wrapper for Comcast-specific services"
```

- Before executing any private extension, verify the file's SHA-256 hash matches the manifest.
- Log a warning (and optionally refuse) if no manifest exists or hashes don't match.

---

## 5. Implementation Completeness

These modules are specified in the directory structure but have placeholder or missing implementations. Prioritized by impact:

| Module | Status in Spec | Priority | Notes |
|--------|---------------|----------|-------|
| `core/memory.py` | Referenced, never defined | **P0** | Central to cross-session continuity. See §1.2 for design. |
| `http_tools/_build_tool()` | `...` placeholder | **P0** | The entire HTTP tool layer depends on this. Must generate Pydantic input models from endpoint parameter schemas and create async callables. |
| `extensions/ms_graph.py` tools | `return []` | **P0** (work persona) | Implement real MS Graph API calls: `mail_list`, `mail_read`, `mail_send`, `calendar_events`, `files_search`, `teams_chat_send`. Use `httpx` + MSAL for auth. |
| `core/graphiti.py` | In directory structure, no implementation | **P1** | Needed before Graphiti-backed memory works. Factory should create per-persona Graphiti clients. |
| `delegation/router.py` | In directory structure, not shown | **P1** | Should contain intent classification logic for automatic delegation routing. |
| `core/observability.py` | Not in spec | **P1** | See §1.1. |
| `core/scheduler.py` | Not in spec | **P1** | See §2.1. |
| `core/resilience.py` | Not in spec | **P2** | See §1.3. |

---

## 6. A2A Protocol Should Be Phase 1

**Problem**: The spec defers A2A to "Future Iterations" (Phase 16). However, [Copilot Studio now supports A2A connections natively](https://learn.microsoft.com/en-us/microsoft-copilot-studio/add-agent-agent-to-agent) as of April 2026, including delegating tasks to external agents over HTTPS.

**Why this matters**: Your agentic-assistant could expose itself as an A2A server, letting your Copilot Studio Chief of Staff (from the Microsoft blueprint) delegate complex research or coding tasks to it. This is the bridge between your Microsoft-native daily workflow and this framework's deeper capabilities.

**Recommendation**: Add `src/assistant/a2a/` module:

```
src/assistant/
├── a2a/
│   ├── __init__.py
│   ├── server.py          # A2A endpoint (FastAPI or Starlette)
│   ├── task_handler.py    # Maps A2A tasks to persona × role × harness
│   └── agent_card.py      # Serves .well-known/agent.json
```

**Implementation guidance**:
- Expose a `/a2a/v1/message:stream` endpoint that accepts A2A task messages from Copilot Studio.
- Serve an [agent card](https://learn.microsoft.com/en-us/microsoft-copilot-studio/add-agent-agent-to-agent) at `.well-known/agent.json` describing capabilities.
- Map incoming A2A tasks to the appropriate persona + role based on task metadata.
- Return results in A2A response format.
- This enables: Copilot Studio (morning briefing trigger) → A2A → agentic-assistant (deep research via Deep Agents harness) → A2A response → Copilot Studio (delivers to Teams).

---

## 7. Minor Fixes

### 7.1 CLI `-h` Flag Conflict
The CLI uses `-h` for `--harness`, which conflicts with Click's default `-h` for `--help`. Change to `-H` or `--harness-name`:
```python
@click.option("--harness", "-H",
              type=click.Choice(["deep_agents", "ms_agent_framework", "auto"]),
              default="auto")
```

### 7.2 SQLAlchemy `text()` Wrapper Missing
In `db.py`, `conn.execute()` receives a raw SQL string. SQLAlchemy async engines require `sqlalchemy.text()`:
```python
from sqlalchemy import text

await conn.execute(text("""
    CREATE TABLE IF NOT EXISTS memory (...)
"""))
```

### 7.3 `deepagents` Package Doesn't Exist Publicly
`uv add deepagents` and `from deepagents import create_deep_agent` reference a package that doesn't appear to exist. Clarify whether this is:
- A custom wrapper you need to build (add to the spec)
- An alias for another package (correct the import)
- Placeholder API design (mark it as such and define the expected interface)

### 7.4 No `pyproject.toml` Entry Point
The CLI module is `assistant.cli` but there's no `[project.scripts]` in `pyproject.toml`. Add:
```toml
[project.scripts]
assistant = "assistant.cli:main"
```
So you can run `uv run assistant -p work` instead of `uv run python -m assistant.cli -p work`.

### 7.5 Persona Config `name` Variable Shadowing
In `PersonaRegistry.load()`, the `tool_sources` dict comprehension uses `name` as the loop variable, which shadows the method's outer scope variable. Rename to `src_name`:
```python
tool_sources={
    src_name: { ... }
    for src_name, src in raw.get("tool_sources", {}).items()
},
```

---

## 8. Recommended Implementation Order

Sequence these by dependency chain and impact:

1. **Memory architecture** (`core/memory.py`, `core/graphiti.py`) — everything downstream depends on coherent memory
2. **HTTP tool builder** (`http_tools/_build_tool()`) — backend integration is non-functional without it
3. **Observability** (`core/observability.py`) — add tracing before the system gets more complex
4. **MS Graph extension** (`extensions/ms_graph.py`) — unlocks the work persona's core value
5. **A2A server** (`a2a/`) — bridges to Copilot Studio Chief of Staff
6. **Scheduler** (`core/scheduler.py`) — enables proactive execution
7. **Obsidian vault integration** — enables RAG over personal knowledge base
8. **Error resilience** (`core/resilience.py`) — retry, circuit breakers, graceful degradation
9. **Extension lifecycle hooks** — initialize/shutdown/refresh
10. **Dynamic harness routing** — auto-select best harness per task
11. **Sub-agent delegation context** — richer context passing to sub-agents
12. **Security hardening** — credential scoping, extension manifest validation
