# agentic-assistant Bootstrap — Autopilot Spec v4.1

## Objective

Create a new **public** repository `agentic-assistant` — a personal AI
assistant with a plugin-based persona system and composable role definitions.
Persona configurations (prompts, memory, role overrides) live in **separate
private repos** mounted as git submodules, enabling version-controlled
configs without exposing sensitive context.

Three repositories:

| Repo | Visibility | Host | Contents |
|------|-----------|------|----------|
| `agentic-assistant` | Public | GitHub | Code, roles, extensions, CLI |
| `assistant-config-work` | Private | Comcast GH Enterprise | Work persona config |
| `assistant-config-personal` | Private | GitHub (private) | Personal persona config |

The assistant orchestrates two existing backend systems via HTTP:

- **agentic-coding-tools** — SW dev harness
- **agentic-content-analyzer** — Knowledge management harness

## What Changed from v4

- **Public repo** — all code, roles, extension implementations are public
- **Private persona configs via git submodules** — each `personas/<name>/`
  directory is a separate private repo mounted as a submodule
- **Extension code lives in public repo** — generic implementations in
  `src/assistant/extensions/`. Private config repos only carry activation
  config and (optionally) proprietary extensions that can't be public
- **Version-controlled memory** — `memory.md` files are tracked in private
  repos, giving you diffable history of learned context
- **Selective initialization** — work machine clones work submodule only,
  personal machine clones personal only, dev machine clones neither

---

## Core Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│             agentic-assistant (PUBLIC REPO)                      │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    Persona × Role Matrix                   │  │
│  │                                                           │  │
│  │              researcher  planner  chief_of_staff  coder   │  │
│  │  work      │  W+R        W+P      W+CoS          W+C    ││  │
│  │  personal  │  P+R        P+P      P+CoS          P+C    ││  │
│  │  future... │  ...        ...      ...            ...     ││  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Persona Configs (GIT SUBMODULES)              │  │
│  │                                                           │  │
│  │  personas/work/ ──→ Comcast GH Enterprise (private)       │  │
│  │  personas/personal/ ──→ GitHub private repo               │  │
│  │  personas/_template/ ──→ tracked in public repo           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Harness Layer (parallel)                      │  │
│  │  Deep Agents │ Claude Code │ Codex │ MS Agent Fw          │  │
│  │  All share: persona configs, roles, HTTP tools, skills    │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              HTTP Tool Layer                               │  │
│  │  agentic-coding-tools ←HTTP→ /help discovery              │  │
│  │  agentic-content-analyzer ←HTTP→ /help discovery          │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Design Principles

1. **Public code, private config** — All code, roles, and extension
   implementations are public. Persona configs (prompts, memory, role
   overrides, credentials) live in private repos mounted as submodules.

2. **Persona = execution boundary** — DB, auth, tools, integrations. Each
   persona is a self-contained directory that maps 1:1 to a private repo.

3. **Role = behavioral pattern** — Prompt, workflow, tool preferences,
   delegation rules. Roles are shared and public. Persona-specific role
   overrides are private.

4. **Persona × Role composition** — Role defines workflow; persona shapes
   tone and constraints. Sub-agents inherit persona, switch role.

5. **Separate databases per persona** — Each gets its own ParadeDB Postgres
   and Graphiti instance.

6. **Version-controlled memory** — `memory.md` accumulates learned context
   and is tracked in the private config repo, giving diffable history.

7. **Harness-agnostic core** — Deep Agents, MS Agent Framework, Claude Code,
   and Codex can all operate on this repo simultaneously.

8. **Selective initialization** — Clone only the persona submodules you need
   on each machine.

---

## Phase 1: Multi-Repo Setup

### 1.1 Create the three repos

**Public repo (GitHub):**
```bash
mkdir agentic-assistant && cd agentic-assistant
git init
uv init --python 3.12

# Core
uv add httpx pydantic-settings pyyaml sqlalchemy asyncpg

# Harness: Deep Agents
uv add deepagents langchain-anthropic

# Harness: MS Agent Framework (Python)
uv add agent-framework agent-framework-anthropic agent-framework-claude

# Dev
uv add --dev pytest ruff mypy

git remote add origin https://github.com/jankneumann/agentic-assistant.git
```

**Work config repo (Comcast GH Enterprise):**
```bash
mkdir assistant-config-work && cd assistant-config-work
git init
# Populate with persona.yaml, prompt.md, memory.md, roles/, extensions/
git remote add origin https://github.comcast.com/jkneumann/assistant-config-work.git
git push -u origin main
```

**Personal config repo (GitHub private):**
```bash
mkdir assistant-config-personal && cd assistant-config-personal
git init
# Populate with persona.yaml, prompt.md, memory.md, roles/, extensions/
git remote add origin https://github.com/jankneumann/assistant-config-personal.git
git push -u origin main
```

### 1.2 Mount submodules

```bash
cd agentic-assistant

# Mount work config (do this on work machines)
git submodule add https://github.comcast.com/jkneumann/assistant-config-work personas/work

# Mount personal config (do this on personal machines)
git submodule add https://github.com/jankneumann/assistant-config-personal personas/personal

# On a machine where you want both
git submodule update --init --recursive
```

### 1.3 .gitmodules (tracked in public repo)

```gitmodules
# Persona configs are private submodules.
# See personas/_template/ for the expected structure.
#
# Setup:
#   git submodule add <your-private-config-repo> personas/<persona-name>
#
# Work machine:
#   git submodule update --init personas/work
#
# Personal machine:
#   git submodule update --init personas/personal

[submodule "personas/work"]
    path = personas/work
    url = https://github.comcast.com/jkneumann/assistant-config-work

[submodule "personas/personal"]
    path = personas/personal
    url = https://github.com/jankneumann/assistant-config-personal
```

### 1.4 .gitignore (public repo)

```gitignore
# Python
__pycache__/
*.pyc
.venv/
dist/
*.egg-info/

# Environment
.env
personas/*.env

# IDE
.vscode/
.idea/

# OS
.DS_Store

# Submodule directories are managed by git submodule, not gitignore.
# If a persona is not initialized, the directory simply won't exist.
```

### 1.5 Convenience setup script

```bash
#!/usr/bin/env bash
# scripts/setup-persona.sh
# Usage: ./scripts/setup-persona.sh <persona-name> <private-repo-url>
#
# Creates a new persona by mounting a private config repo as a submodule.
# If the private repo doesn't exist yet, creates it from _template.

set -euo pipefail

PERSONA_NAME="${1:?Usage: setup-persona.sh <persona-name> <private-repo-url>}"
PRIVATE_URL="${2:?Usage: setup-persona.sh <persona-name> <private-repo-url>}"

if [ -d "personas/${PERSONA_NAME}" ]; then
    echo "Persona '${PERSONA_NAME}' already exists. Run: git submodule update --init personas/${PERSONA_NAME}"
    exit 1
fi

echo "Mounting persona '${PERSONA_NAME}' from ${PRIVATE_URL}..."
git submodule add "${PRIVATE_URL}" "personas/${PERSONA_NAME}"
echo "Done. Edit personas/${PERSONA_NAME}/persona.yaml to configure."
```

```bash
#!/usr/bin/env bash
# scripts/init-persona-repo.sh
# Usage: ./scripts/init-persona-repo.sh <target-dir>
#
# Initializes a new private persona config repo from _template.

set -euo pipefail

TARGET="${1:?Usage: init-persona-repo.sh <target-dir>}"

if [ -d "${TARGET}" ]; then
    echo "Directory '${TARGET}' already exists."
    exit 1
fi

cp -r personas/_template "${TARGET}"
cd "${TARGET}"
git init
git add .
git commit -m "Initial persona config from template"
echo "Done. Add a remote and push: git remote add origin <url> && git push -u origin main"
```

---

## Phase 2: Directory Structure

### 2.1 Public repo (agentic-assistant)

```
agentic-assistant/                     # PUBLIC REPO
│
├── .claude/
│   ├── settings.json
│   └── commands/
│       ├── work.md
│       ├── personal.md
│       ├── researcher.md
│       └── chief_of_staff.md
├── .codex/
│   └── skills/
├── .gemini/
│   └── settings.json
├── .gitmodules                        # Submodule references
├── AGENTS.md                          # Deep Agents persistent memory
├── CLAUDE.md                          # Claude Code project context
│
├── roles/                             # SHARED ROLE DEFINITIONS (public)
│   ├── _template/
│   │   ├── role.yaml
│   │   └── prompt.md
│   ├── researcher/
│   │   ├── role.yaml
│   │   ├── prompt.md
│   │   └── skills/
│   │       └── deep_research.md
│   ├── planner/
│   │   ├── role.yaml
│   │   ├── prompt.md
│   │   └── skills/
│   │       └── strategic_planning.md
│   ├── chief_of_staff/
│   │   ├── role.yaml
│   │   ├── prompt.md
│   │   └── skills/
│   │       ├── briefing.md
│   │       ├── delegation.md
│   │       └── triage.md
│   ├── writer/
│   │   ├── role.yaml
│   │   ├── prompt.md
│   │   └── skills/
│   │       └── content_drafting.md
│   └── coder/
│       ├── role.yaml
│       ├── prompt.md
│       └── skills/
│           └── code_analysis.md
│
├── personas/                          # SUBMODULE MOUNT POINTS
│   ├── _template/                     # Template (tracked in public repo)
│   │   ├── persona.yaml
│   │   ├── prompt.md
│   │   ├── memory.md
│   │   ├── tools.yaml
│   │   ├── roles/
│   │   │   └── .gitkeep
│   │   └── extensions/
│   │       └── .gitkeep
│   ├── work/                          # ← submodule → Comcast GH Enterprise
│   └── personal/                      # ← submodule → GitHub private repo
│
├── src/
│   └── assistant/
│       ├── __init__.py
│       │
│       ├── core/                      # HARNESS-AGNOSTIC CORE (public)
│       │   ├── __init__.py
│       │   ├── persona.py            # Persona registry + loader
│       │   ├── role.py               # Role registry + merger
│       │   ├── composition.py        # Persona × Role prompt composition
│       │   ├── config.py             # Config schema
│       │   ├── db.py                 # DB connection factory (per-persona)
│       │   ├── graphiti.py           # Graphiti client factory (per-persona)
│       │   ├── memory.py             # Memory read/write (DB-backed)
│       │   └── http_tools/
│       │       ├── __init__.py
│       │       ├── client.py
│       │       ├── discovery.py
│       │       └── registry.py
│       │
│       ├── harnesses/                 # HARNESS ADAPTERS (public)
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── factory.py
│       │   ├── deep_agents.py
│       │   └── ms_agent_fw.py
│       │
│       ├── extensions/                # EXTENSION IMPLEMENTATIONS (public)
│       │   ├── __init__.py
│       │   ├── base.py               # Extension protocol
│       │   ├── ms_graph.py           # MS Graph (generic impl)
│       │   ├── teams.py              # Teams (generic impl)
│       │   ├── sharepoint.py         # SharePoint (generic impl)
│       │   ├── outlook.py            # Outlook (generic impl)
│       │   ├── gmail.py              # Gmail (generic impl)
│       │   ├── gcal.py               # Google Calendar (generic impl)
│       │   └── gdrive.py            # Google Drive (generic impl)
│       │
│       ├── delegation/                # SUB-AGENT DELEGATION (public)
│       │   ├── __init__.py
│       │   ├── spawner.py
│       │   └── router.py
│       │
│       └── cli.py
│
├── scripts/
│   ├── setup-persona.sh              # Mount a private config repo
│   └── init-persona-repo.sh          # Create new config repo from template
│
├── tests/
│   ├── test_persona_registry.py
│   ├── test_role_registry.py
│   ├── test_composition.py
│   ├── test_persona_isolation.py
│   ├── test_http_tools.py
│   ├── test_delegation.py
│   ├── test_deep_agents_harness.py
│   ├── test_ms_agent_fw_harness.py
│   └── test_extensions.py
│
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

### 2.2 Private config repo structure (assistant-config-work)

```
assistant-config-work/                 # PRIVATE — Comcast GH Enterprise
├── persona.yaml                       # DB connection, auth, harness config
├── prompt.md                          # Work-specific prompt augmentation
├── memory.md                          # Learned context (version controlled!)
├── tools.yaml                         # Work-allowed tools
├── roles/                             # Work-specific role overrides
│   ├── researcher.yaml
│   ├── chief_of_staff.yaml
│   ├── writer.yaml
│   └── coder.yaml
└── extensions/                        # ONLY for proprietary extensions
    └── comcast_internal_api.py        # Things that can't be public
```

### 2.3 Private config repo structure (assistant-config-personal)

```
assistant-config-personal/             # PRIVATE — GitHub private repo
├── persona.yaml
├── prompt.md
├── memory.md
├── tools.yaml
├── roles/
│   ├── researcher.yaml
│   └── chief_of_staff.yaml
└── extensions/                        # Personal-only extensions (if any)
    └── .gitkeep
```

---

## Phase 3: Persona Template

### 3.1 Template persona.yaml (personas/_template/persona.yaml)

```yaml
# Persona definition template
# Copy this directory to create a new private persona config repo.

name: template
display_name: "Template Persona"

# ── Database (each persona gets its own instance) ──
database:
  url_env: TEMPLATE_DATABASE_URL       # Env var holding connection string

# ── Knowledge Graph ──
graphiti:
  url_env: TEMPLATE_GRAPHITI_URL

# ── Authentication ──
auth:
  provider: custom                     # microsoft | google | custom
  config: {}
    # Add env var references for auth credentials
    # e.g., tenant_id_env: WORK_MS_TENANT_ID

# ── Harnesses ──
harnesses:
  deep_agents:
    enabled: true
    model: "anthropic:claude-sonnet-4-20250514"
    memory_files:
      - "./AGENTS.md"
      # Add: "./personas/<name>/memory.md"
    skills_dir: "./src/assistant/skills"

  ms_agent_framework:
    enabled: false
    model: "anthropic:claude-sonnet-4-20250514"
    foundry_endpoint_env: ""
    extensions: []

  claude_code:
    enabled: true

  codex:
    enabled: true

# ── Default role ──
default_role: chief_of_staff

# ── Roles disabled for this persona ──
disabled_roles: []

# ── HTTP Tool Sources ──
tool_sources:
  content_analyzer:
    base_url_env: CONTENT_ANALYZER_URL
    auth_header_env: ""
    allowed_tools: []

  coding_tools:
    base_url_env: CODING_TOOLS_URL
    auth_header_env: ""
    allowed_tools: []

# ── Extensions ──
# Extensions are loaded from two locations:
#   1. Public: src/assistant/extensions/ (generic implementations)
#   2. Private: personas/<name>/extensions/ (proprietary implementations)
# The 'module' field is resolved in order: private first, then public.
extensions: []
```

### 3.2 Template prompt.md (personas/_template/prompt.md)

```markdown
## Persona Context

Describe the persona's operating context here:
- What systems does this persona have access to?
- What constraints apply?
- What communication style is expected?
- What is the active context?
```

### 3.3 Template memory.md (personas/_template/memory.md)

```markdown
# Persona Memory

## Learned Preferences
<!-- Agent appends here as it learns across sessions -->

## Active Projects
<!-- Track ongoing work relevant to this persona -->

## Interaction Patterns
<!-- Agent notes recurring patterns and preferences -->
```

---

## Phase 4: Work Persona Config (assistant-config-work)

### 4.1 persona.yaml

```yaml
name: work
display_name: "Work (Comcast)"

database:
  url_env: WORK_DATABASE_URL

graphiti:
  url_env: WORK_GRAPHITI_URL

auth:
  provider: microsoft
  config:
    tenant_id_env: WORK_MS_TENANT_ID
    client_id_env: WORK_MS_CLIENT_ID
    client_secret_env: WORK_MS_CLIENT_SECRET

harnesses:
  deep_agents:
    enabled: true
    model: "anthropic:claude-sonnet-4-20250514"
    memory_files:
      - "./AGENTS.md"
      - "./personas/work/memory.md"
    skills_dir: "./src/assistant/skills"

  ms_agent_framework:
    enabled: true
    model: "anthropic:claude-sonnet-4-20250514"
    foundry_endpoint_env: WORK_FOUNDRY_ENDPOINT
    extensions:
      - ms_graph
      - teams
      - sharepoint
      - outlook

  claude_code:
    enabled: true

  codex:
    enabled: true

default_role: chief_of_staff
disabled_roles: []

tool_sources:
  content_analyzer:
    base_url_env: CONTENT_ANALYZER_URL
    auth_header_env: CONTENT_ANALYZER_AUTH
    allowed_tools: []

  coding_tools:
    base_url_env: CODING_TOOLS_URL
    auth_header_env: CODING_TOOLS_AUTH
    allowed_tools: []

# Extensions loaded from public repo (src/assistant/extensions/)
# unless a private override exists in personas/work/extensions/
extensions:
  - name: ms_graph
    module: ms_graph                   # Resolves to src/assistant/extensions/ms_graph.py
    config:
      scopes:
        - "Mail.ReadWrite"
        - "Calendars.ReadWrite"
        - "Files.ReadWrite"
        - "Chat.ReadWrite"
  - name: teams
    module: teams
  - name: sharepoint
    module: sharepoint
  - name: outlook
    module: outlook
```

### 4.2 prompt.md

```markdown
## Work Persona Context

You are operating in Jan's **work context** at Comcast Cable.

### Access
- Microsoft Outlook, Teams, SharePoint, OneDrive via MS Graph API
- All agentic-coding-tools capabilities (repos, PRs, agent coordination)
- All agentic-content-analyzer capabilities (newsletter archive, knowledge graph)

### Constraints
- Do not access or reference personal Google services
- Content produced may be shared with senior leadership — maintain professional tone
- IP sensitivity: do not include proprietary Comcast information in external tool calls
- All memory is stored in this persona's dedicated database

### Active work context
- Weekly AI industry updates for CTO and Chief Data and AI Officer
- Strategic oversight of AI/ML tooling and multi-agent coordination systems
- Newsletter aggregator pipeline operations and improvements
```

### 4.3 memory.md (starts empty, agent populates over time)

```markdown
# Work Persona Memory

## Learned Preferences
<!-- Agent appends here -->

## Active Projects

## Interaction Patterns
```

### 4.4 Role overrides (roles/)

**roles/researcher.yaml:**
```yaml
prompt_append: |
  ### Work Context Additions
  - All research output should be calibrated for senior leadership consumption
  - Include strategic implications for Comcast AI/Data strategy specifically
  - Flag competitive intelligence and market positioning insights
  - Use the weekly AI update format when producing trend analysis
  - Do not include proprietary Comcast information in external tool calls
  - When citing sources, include publication date for recency assessment

additional_preferred_tools:
  - ms_graph:sharepoint_search

delegation_overrides:
  max_concurrent: 2

context_overrides:
  output_format: "structured"
```

**roles/chief_of_staff.yaml:**
```yaml
prompt_append: |
  ### Work Context Additions
  - Briefings should be formatted for senior leadership consumption
  - Flag items relevant to CTO and Chief Data and AI Officer priorities
  - For communications: use Microsoft Teams and Outlook via MS Graph extensions
  - Calendar operations use Outlook calendar
  - Include competitive intelligence section in weekly briefings
  - When drafting emails to leadership, use formal but concise tone

additional_preferred_tools:
  - ms_graph:mail_send
  - ms_graph:calendar_events
  - ms_graph:teams_chat

delegation_overrides:
  max_concurrent: 3
```

**roles/writer.yaml:**
```yaml
prompt_append: |
  ### Work Context Additions
  - All work writing targets senior technical leadership
  - Weekly AI updates follow the established format:
    Top themes → Detail per theme → Strategic implications → Recommendations
  - Emails to leadership: brief, action-oriented, decisions at the top
  - Never include speculative content without labeling it as such
```

**roles/coder.yaml:**
```yaml
prompt_append: |
  ### Work Context Additions
  - Follow Comcast coding standards and review processes
  - All PRs require proper description and linked issues
  - Be cautious with any operations that could affect production
  - IP considerations: flag any use of external code that could have
    licensing implications
```

---

## Phase 5: Personal Persona Config (assistant-config-personal)

### 5.1 persona.yaml

```yaml
name: personal
display_name: "Personal"

database:
  url_env: PERSONAL_DATABASE_URL

graphiti:
  url_env: PERSONAL_GRAPHITI_URL

auth:
  provider: google
  config:
    client_id_env: PERSONAL_GOOGLE_CLIENT_ID
    client_secret_env: PERSONAL_GOOGLE_CLIENT_SECRET
    refresh_token_env: PERSONAL_GOOGLE_REFRESH_TOKEN

harnesses:
  deep_agents:
    enabled: true
    model: "anthropic:claude-sonnet-4-20250514"
    memory_files:
      - "./AGENTS.md"
      - "./personas/personal/memory.md"
    skills_dir: "./src/assistant/skills"

  ms_agent_framework:
    enabled: false

  claude_code:
    enabled: true

  codex:
    enabled: true

default_role: chief_of_staff
disabled_roles: []

tool_sources:
  content_analyzer:
    base_url_env: CONTENT_ANALYZER_URL
    allowed_tools: []

  coding_tools:
    base_url_env: CODING_TOOLS_URL
    allowed_tools: []

extensions:
  - name: gmail
    module: gmail
    config:
      scopes:
        - "https://www.googleapis.com/auth/gmail.modify"
  - name: gcal
    module: gcal
    config:
      scopes:
        - "https://www.googleapis.com/auth/calendar"
  - name: gdrive
    module: gdrive
    config:
      scopes:
        - "https://www.googleapis.com/auth/drive"
```

### 5.2 prompt.md

```markdown
## Personal Persona Context

You are operating in Jan's **personal context**.

### Access
- Gmail, Google Calendar, Google Drive via Google APIs
- All agentic-coding-tools capabilities (personal repos, side projects)
- All agentic-content-analyzer capabilities (personal research, learning)

### Constraints
- Do not access or reference Microsoft/Comcast work services
- Tone can be more casual and exploratory
- All memory is stored in this persona's dedicated database

### Active personal context
- Personal AI tooling exploration and hobby projects
- Learning and research interests
```

### 5.3 Role overrides (roles/)

**roles/researcher.yaml:**
```yaml
prompt_append: |
  ### Personal Context Additions
  - Tone can be more exploratory and speculative
  - Include "things to try" and hands-on experiment suggestions
  - Connect findings to personal projects and learning goals
  - It's fine to go deep into rabbit holes if the topic is interesting
  - Emphasize practical takeaways and implementation ideas

context_overrides:
  output_format: "conversational"
```

**roles/chief_of_staff.yaml:**
```yaml
prompt_append: |
  ### Personal Context Additions
  - Briefings can be more casual and interest-driven
  - Calendar operations use Google Calendar
  - Communications use Gmail
  - Prioritize learning opportunities and interesting experiments
  - It's fine to include tangential but interesting items

additional_preferred_tools:
  - gmail:send
  - gcal:events
  - gdrive:search
```

---

## Phase 6: Role Definitions (Public Repo)

### 6.1 Researcher (roles/researcher/)

**role.yaml:**
```yaml
name: researcher
display_name: "Researcher"
description: "Deep research and analysis with source synthesis"

preferred_tools:
  - content_analyzer:search
  - content_analyzer:knowledge_graph
  - content_analyzer:newsletter_archive

delegation:
  can_spawn_sub_agents: true
  max_concurrent: 3
  allowed_sub_roles:
    - writer
    - coder

planning:
  always_plan: true
  decomposition_style: "breadth_first"
  max_depth: 3

context:
  prioritize_sources: true
  save_findings: true
  output_format: "structured"

skills_dir: "./roles/researcher/skills"
prompt_position: "after_persona"
```

**prompt.md:**
```markdown
## Role: Researcher

You are operating as a **researcher**. Your primary objective is thorough,
source-grounded analysis.

### Behavioral Rules
- Always decompose research questions before diving in
- Query the knowledge graph first to check for existing coverage
- Search the newsletter archive for prior analysis before generating new
- Cite sources for every claim — never synthesize without attribution
- When you find gaps, flag them explicitly rather than filling with inference
- Save intermediate findings to the filesystem for future reference

### Output Structure
1. Executive summary (2-3 sentences)
2. Key findings with source attribution
3. Connections to active projects (check AGENTS.md and persona memory)
4. Open questions and recommended next steps

### Tool Preferences
- Start with knowledge graph queries (broad context)
- Then newsletter archive search (specific coverage)
- Use coding-tools only if the research involves code analysis

### Delegation
- If research requires content drafting, delegate to **writer** sub-role
- If research involves code analysis, delegate to **coder** sub-role
- Always review sub-agent output before incorporating into final synthesis
```

**skills/deep_research.md:**
```markdown
# Skill: Deep Research

## When to use
Investigating a topic requiring multiple sources, synthesis across the
newsletter archive, and structured output.

## Workflow
1. **Plan**: Decompose the research question into sub-questions
2. **Context check**: Query knowledge graph for existing entities/relationships
3. **Archive search**: Search newsletter archive for prior coverage
4. **Gap analysis**: Identify covered vs. uncovered areas
5. **Synthesis**: Combine findings into structured output
6. **Persist**: Save findings, update knowledge graph if new entities found

## Decision Tree
- Strong existing coverage → summarize, note what's new
- Partial coverage → fill gaps with targeted searches
- Novel topic → flag as emerging, provide best available context
- Cross-domain → spawn sub-agents for domain-specific research
```

### 6.2 Planner (roles/planner/)

**role.yaml:**
```yaml
name: planner
display_name: "Planner"
description: "Strategic planning, roadmap development, initiative structuring"

preferred_tools:
  - content_analyzer:knowledge_graph
  - coding_tools:repo_status
  - coding_tools:github_issues

delegation:
  can_spawn_sub_agents: true
  max_concurrent: 2
  allowed_sub_roles:
    - researcher
    - writer

planning:
  always_plan: true
  decomposition_style: "goal_oriented"
  max_depth: 4

context:
  prioritize_sources: false
  save_findings: true
  output_format: "structured"

skills_dir: "./roles/planner/skills"
prompt_position: "after_persona"
```

**prompt.md:**
```markdown
## Role: Planner

You are operating as a **strategic planner**. Your primary objective is
turning goals into actionable plans with clear milestones.

### Behavioral Rules
- Start by clarifying the objective and success criteria
- Break down goals into phases with dependencies
- Identify risks and mitigation strategies for each phase
- Cross-reference with active projects to find synergies or conflicts
- Produce timelines that account for realistic constraints

### Output Structure
1. Objective statement and success criteria
2. Phased plan with milestones
3. Dependencies and critical path
4. Risks and mitigations
5. Resource requirements and tool recommendations

### Delegation
- Market research → delegate to **researcher**
- Written deliverables → delegate to **writer**
```

### 6.3 Chief of Staff (roles/chief_of_staff/)

**role.yaml:**
```yaml
name: chief_of_staff
display_name: "Chief of Staff"
description: "Executive assistant — triage, briefings, delegation, communications"

preferred_tools:
  - content_analyzer:daily_digest
  - content_analyzer:weekly_digest
  - content_analyzer:knowledge_graph

delegation:
  can_spawn_sub_agents: true
  max_concurrent: 5
  allowed_sub_roles:
    - researcher
    - writer
    - planner
    - coder

planning:
  always_plan: false
  decomposition_style: "priority_first"

context:
  prioritize_sources: false
  output_format: "brief"

skills_dir: "./roles/chief_of_staff/skills"
prompt_position: "after_persona"
```

**prompt.md:**
```markdown
## Role: Chief of Staff

You are operating as Jan's **chief of staff**. You triage, delegate, and
synthesize.

### Behavioral Rules
- Triage incoming requests: handle simple ones directly, delegate complex
  ones to appropriate sub-roles
- For briefings: pull latest digest, cross-reference with active projects,
  rank by strategic relevance
- For communications: draft in the persona's appropriate tone, always offer
  review before sending
- For scheduling: check calendar context, suggest optimal times, flag conflicts
- Proactively connect dots — if a newsletter item relates to an active project,
  surface it without being asked

### Delegation Patterns
- Research questions → spawn **researcher** sub-agent
- Content drafting → spawn **writer** sub-agent
- Code-related tasks → spawn **coder** sub-agent
- Strategic planning → spawn **planner** sub-agent
- Simple factual lookups → handle directly, don't over-delegate

### Triage Framework
1. **Urgent + Simple** → handle directly, immediately
2. **Urgent + Complex** → spawn sub-agent, monitor actively
3. **Important + Simple** → handle directly, queue appropriately
4. **Important + Complex** → plan first, then delegate with clear briefs
5. **Informational** → note for next briefing

### Communication Style
- Brief and actionable
- Lead with the decision or action needed, then context
```

**skills/briefing.md:**
```markdown
# Skill: Briefing Generation

## When to use
User asks for a briefing, update, "what's new", or morning summary.

## Workflow
1. Query content-analyzer for latest digest (daily or weekly)
2. Load active projects from AGENTS.md and persona memory
3. Cross-reference digest items with active projects
4. Rank by strategic relevance
5. Check for connections to past conversations or research
6. Format per persona communication style

## Output
- Top 3-5 items ranked by strategic relevance
- For each: one-line summary + why it matters + suggested action
- "Connecting threads" — items relating to ongoing work
- "Decisions needed" section if applicable
```

**skills/delegation.md:**
```markdown
# Skill: Task Delegation to Sub-Agents

## When to use
Task is too complex to handle directly.

## Workflow
1. Classify task type (research, writing, coding, planning)
2. Select appropriate sub-role
3. Compose delegation brief: objective, context, constraints, format, priority
4. Spawn sub-agent with role + current persona
5. Monitor progress
6. Review output and integrate

## Decision Rules
- Multi-domain → spawn multiple sub-agents in parallel
- Dependencies → spawn sequentially, pass output forward
- Insufficient output → feedback and re-delegate
- Never exceed `delegation.max_concurrent`
```

**skills/triage.md:**
```markdown
# Skill: Request Triage

## When to use
Every incoming message (runs implicitly).

## Workflow
1. Classify intent: question, task, briefing, communication, scheduling,
   research, code, meta
2. Assess complexity: simple (handle directly) vs complex (delegate)
3. Check persona context: are required tools available?
4. Route per triage framework

## Signals
- "?" or question words → question/research
- "write/draft/compose" → writer sub-role
- "plan/roadmap/strategy" → planner sub-role
- "code/bug/PR/repo" → coder sub-role
- "briefing/update/news" → handle directly
- "email/message" → handle with persona-appropriate tools
```

### 6.4 Writer (roles/writer/)

**role.yaml:**
```yaml
name: writer
display_name: "Writer"
description: "Content drafting — emails, reports, presentations, posts"

preferred_tools:
  - content_analyzer:knowledge_graph
  - content_analyzer:search

delegation:
  can_spawn_sub_agents: false
  max_concurrent: 0

planning:
  always_plan: false
  decomposition_style: "outline_first"

context:
  prioritize_sources: true
  save_findings: false
  output_format: "conversational"

skills_dir: "./roles/writer/skills"
prompt_position: "after_persona"
```

**prompt.md:**
```markdown
## Role: Writer

You are operating as a **writer**. Your primary objective is clear, polished
content that serves the intended audience.

### Behavioral Rules
- Always clarify the audience and purpose before drafting
- Adapt tone to the persona context (formal for work, casual for personal)
- For long-form: outline first, then draft section by section
- For communications: be concise, lead with the key message
- Always offer to iterate — first drafts are starting points

### Output Approach
- Emails: subject line + body, persona-appropriate tone
- Reports: executive summary + sections, cite sources
- Presentations: key message per slide, minimal text
- Posts/articles: hook + body + conclusion, audience-calibrated
```

### 6.5 Coder (roles/coder/)

**role.yaml:**
```yaml
name: coder
display_name: "Coder"
description: "Code analysis, implementation, debugging, repo operations"

preferred_tools:
  - coding_tools:repo_status
  - coding_tools:github_issues
  - coding_tools:github_prs
  - coding_tools:file_read
  - coding_tools:agent_coordinate

delegation:
  can_spawn_sub_agents: false
  max_concurrent: 0

planning:
  always_plan: true
  decomposition_style: "task_oriented"

context:
  prioritize_sources: false
  save_findings: true
  output_format: "structured"

skills_dir: "./roles/coder/skills"
prompt_position: "after_persona"
```

**prompt.md:**
```markdown
## Role: Coder

You are operating as a **coder**. Your primary objective is correct,
well-structured code and clear technical analysis.

### Behavioral Rules
- Always read existing code before modifying
- Use the coding-tools HTTP API for repo operations
- For multi-file changes: plan the change set, then execute
- Test your changes before declaring done
- Respect the repo's existing conventions (CLAUDE.md, AGENTS.md)
- For agent coordination, use worktree isolation patterns

### Delegation
- Coders don't delegate — report back to parent if research or writing needed

### Output
- Code with comments explaining the "why"
- Summary of changes
- Test results or suggested test approach
```

---

## Phase 7: Core Library Implementation

### 7.1 Persona registry (src/assistant/core/persona.py)

```python
"""Persona registry — discovers submodule-mounted persona configs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class PersonaConfig:
    name: str
    display_name: str
    database_url: str
    graphiti_url: str
    auth_provider: str
    auth_config: dict[str, str]
    harnesses: dict[str, dict[str, Any]]
    tool_sources: dict[str, dict[str, Any]]
    extensions: list[dict[str, Any]]
    extensions_dir: Path
    default_role: str = "chief_of_staff"
    disabled_roles: list[str] = field(default_factory=list)
    prompt_augmentation: str = ""
    memory_content: str = ""
    raw: dict = field(default_factory=dict)


class PersonaRegistry:
    """Discovers personas from submodule-mounted directories."""

    def __init__(self, personas_dir: Path = Path("personas")):
        self.personas_dir = personas_dir
        self._cache: dict[str, PersonaConfig] = {}

    def discover(self) -> list[str]:
        """List initialized persona submodules."""
        return [
            p.name for p in sorted(self.personas_dir.iterdir())
            if p.is_dir()
            and (p / "persona.yaml").exists()
            and not p.name.startswith("_")
        ]

    def load(self, name: str) -> PersonaConfig:
        if name in self._cache:
            return self._cache[name]

        persona_dir = self.personas_dir / name
        config_path = persona_dir / "persona.yaml"
        if not config_path.exists():
            available = self.discover()
            hint = (
                f" Initialize with: git submodule update --init personas/{name}"
                if (persona_dir / ".git").exists() or not persona_dir.exists()
                else ""
            )
            raise ValueError(
                f"Persona '{name}' not found or not initialized. "
                f"Available: {available}.{hint}"
            )

        with open(config_path) as f:
            raw = yaml.safe_load(f)

        config = PersonaConfig(
            name=raw["name"],
            display_name=raw["display_name"],
            database_url=_env(raw["database"]["url_env"]),
            graphiti_url=_env(raw["graphiti"]["url_env"]),
            auth_provider=raw["auth"]["provider"],
            auth_config={k: _env(v) for k, v in raw["auth"]["config"].items()},
            harnesses=raw.get("harnesses", {}),
            tool_sources={
                name: {
                    "base_url": _env(src.get("base_url_env", "")),
                    "auth_header": _env(src.get("auth_header_env", "")),
                    "allowed_tools": src.get("allowed_tools", []),
                }
                for name, src in raw.get("tool_sources", {}).items()
            },
            extensions=raw.get("extensions", []),
            extensions_dir=Path(
                raw.get("extensions_dir", persona_dir / "extensions")
            ),
            default_role=raw.get("default_role", "chief_of_staff"),
            disabled_roles=raw.get("disabled_roles", []),
            raw=raw,
        )

        # Load prompt and memory from private config repo
        prompt_path = persona_dir / "prompt.md"
        if prompt_path.exists():
            config.prompt_augmentation = prompt_path.read_text()

        memory_path = persona_dir / "memory.md"
        if memory_path.exists():
            config.memory_content = memory_path.read_text()

        self._cache[name] = config
        return config

    def load_extensions(self, config: PersonaConfig) -> list[Any]:
        """Load extensions — check private repo first, fall back to public."""
        from importlib import import_module as imp
        extensions = []
        for ext_def in config.extensions:
            module_name = ext_def["module"]
            ext = None

            # 1. Try private persona extensions dir first
            private_path = config.extensions_dir / f"{module_name}.py"
            if private_path.exists():
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    f"persona_ext_{config.name}_{module_name}", private_path
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                ext = mod.create_extension(ext_def.get("config", {}))

            # 2. Fall back to public extensions
            if ext is None:
                try:
                    mod = imp(f"assistant.extensions.{module_name}")
                    ext = mod.create_extension(ext_def.get("config", {}))
                except ImportError as e:
                    print(f"Warning: Extension {module_name} not found: {e}")
                    continue

            extensions.append(ext)
        return extensions


def _env(var_name: str) -> str:
    return os.environ.get(var_name, "") if var_name else ""
```

### 7.2 Role registry (src/assistant/core/role.py)

```python
"""Role registry — shared roles with persona-specific overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from assistant.core.persona import PersonaConfig


@dataclass
class RoleConfig:
    name: str
    display_name: str
    description: str
    prompt: str
    preferred_tools: list[str] = field(default_factory=list)
    delegation: dict[str, Any] = field(default_factory=dict)
    planning: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    skills_dir: str = ""
    raw: dict = field(default_factory=dict)


class RoleRegistry:

    def __init__(
        self,
        roles_dir: Path = Path("roles"),
        personas_dir: Path = Path("personas"),
    ):
        self.roles_dir = roles_dir
        self.personas_dir = personas_dir

    def discover(self) -> list[str]:
        return [
            p.name for p in sorted(self.roles_dir.iterdir())
            if p.is_dir()
            and (p / "role.yaml").exists()
            and not p.name.startswith("_")
        ]

    def available_for_persona(self, persona: PersonaConfig) -> list[str]:
        return [r for r in self.discover() if r not in persona.disabled_roles]

    def load(self, role_name: str, persona: PersonaConfig) -> RoleConfig:
        # 1. Load base role from public repo
        base_path = self.roles_dir / role_name
        if not (base_path / "role.yaml").exists():
            raise ValueError(
                f"Role '{role_name}' not found. Available: {self.discover()}"
            )

        with open(base_path / "role.yaml") as f:
            base = yaml.safe_load(f)

        base_prompt = ""
        if (base_path / "prompt.md").exists():
            base_prompt = (base_path / "prompt.md").read_text()

        # 2. Load persona-specific overrides from private config repo
        override_path = (
            self.personas_dir / persona.name / "roles" / f"{role_name}.yaml"
        )
        override = {}
        if override_path.exists():
            with open(override_path) as f:
                override = yaml.safe_load(f) or {}

        # 3. Merge
        merged_prompt = base_prompt
        if override.get("prompt_append"):
            merged_prompt += f"\n\n{override['prompt_append']}"

        preferred_tools = list(base.get("preferred_tools", []))
        if override.get("additional_preferred_tools"):
            preferred_tools.extend(override["additional_preferred_tools"])

        delegation = dict(base.get("delegation", {}))
        if override.get("delegation_overrides"):
            delegation.update(override["delegation_overrides"])

        context = dict(base.get("context", {}))
        if override.get("context_overrides"):
            context.update(override["context_overrides"])

        return RoleConfig(
            name=base["name"],
            display_name=base["display_name"],
            description=base["description"],
            prompt=merged_prompt,
            preferred_tools=preferred_tools,
            delegation=delegation,
            planning=base.get("planning", {}),
            context=context,
            skills_dir=base.get("skills_dir", ""),
            raw={**base, **override},
        )
```

### 7.3 Prompt composition (src/assistant/core/composition.py)

```python
"""Three-layer prompt composition: base → persona → role."""

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig


BASE_SYSTEM_PROMPT = """You are Jan's personal AI assistant. You operate within
a specific persona (execution boundary) and role (behavioral pattern).

You have access to specialized backend systems via HTTP tools and
persona-specific integrations. Route tasks appropriately, maintain
cross-session memory, and respect persona boundaries.

## Core Rules
- Be direct and substantive; avoid filler
- Respect persona boundaries — never access tools or data outside your
  active persona's scope
- When delegating to sub-agents, they inherit your persona but can switch roles
- Update memory with learned preferences and patterns
- For complex tasks, use planning tools to decompose before executing
"""


def compose_system_prompt(
    persona: PersonaConfig,
    role: RoleConfig,
) -> str:
    layers = [BASE_SYSTEM_PROMPT]

    if persona.prompt_augmentation:
        layers.append(persona.prompt_augmentation)

    if role.prompt:
        layers.append(role.prompt)

    layers.append(_build_active_context(persona, role))

    return "\n\n---\n\n".join(layers)


def _build_active_context(persona: PersonaConfig, role: RoleConfig) -> str:
    parts = [
        f"## Active Configuration",
        f"- **Persona**: {persona.display_name}",
        f"- **Role**: {role.display_name}",
        f"- **Sub-roles**: "
        f"{', '.join(role.delegation.get('allowed_sub_roles', ['none']))}",
    ]
    if role.planning.get("always_plan"):
        parts.append("- **Planning**: Always plan before executing")
    if role.preferred_tools:
        parts.append(f"- **Preferred tools**: {', '.join(role.preferred_tools)}")
    return "\n".join(parts)
```

### 7.4 Database factory (src/assistant/core/db.py)

```python
"""Per-persona database connection factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from assistant.core.persona import PersonaConfig

_engines: dict[str, AsyncEngine] = {}


async def get_engine(persona: PersonaConfig) -> AsyncEngine:
    if persona.name not in _engines:
        if not persona.database_url:
            raise RuntimeError(
                f"No database URL for persona '{persona.name}'. "
                f"Set {persona.raw['database']['url_env']}."
            )
        _engines[persona.name] = create_async_engine(
            persona.database_url, pool_size=5, max_overflow=10,
        )
    return _engines[persona.name]


async def init_schema(persona: PersonaConfig) -> None:
    engine = await get_engine(persona)
    async with engine.begin() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                key TEXT NOT NULL UNIQUE,
                value JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS preferences (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                category TEXT NOT NULL,
                key TEXT NOT NULL,
                value JSONB NOT NULL,
                learned_from TEXT,
                confidence FLOAT DEFAULT 0.5,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(category, key)
            );
            CREATE TABLE IF NOT EXISTS interactions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id TEXT,
                harness TEXT,
                role TEXT,
                tool_calls JSONB,
                routing_decisions JSONB,
                delegation_log JSONB,
                feedback TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
```

### 7.5 HTTP tool discovery (src/assistant/core/http_tools/discovery.py)

```python
"""Dynamic tool discovery via /help endpoints."""

from __future__ import annotations

import httpx
from langchain_core.tools import StructuredTool


async def discover_tools(
    base_url: str,
    auth_headers: dict | None = None,
    allowed_tools: list[str] | None = None,
) -> list[StructuredTool]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{base_url}/help", headers=auth_headers or {},
        )
        response.raise_for_status()
        catalog = response.json()

    tools = []
    for endpoint in catalog.get("endpoints", []):
        name = endpoint["name"]
        if allowed_tools and name not in allowed_tools:
            continue
        tool = _build_tool(base_url, endpoint, auth_headers)
        tools.append(tool)
    return tools


def _build_tool(base_url, endpoint, auth_headers) -> StructuredTool:
    # TODO: Build Pydantic input model from endpoint["parameters"]
    # TODO: Create async callable that POSTs to endpoint
    # TODO: Return StructuredTool(name, description, func, args_schema)
    ...
```

---

## Phase 8: Harness Adapters

### 8.1 Base (src/assistant/harnesses/base.py)

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig


class HarnessAdapter(ABC):
    def __init__(self, persona: PersonaConfig, role: RoleConfig):
        self.persona = persona
        self.role = role

    @abstractmethod
    async def create_agent(self, tools: list, extensions: list) -> Any: ...

    @abstractmethod
    async def invoke(self, agent: Any, message: str) -> str: ...

    @abstractmethod
    async def spawn_sub_agent(
        self, role: RoleConfig, task: str, tools: list, extensions: list,
    ) -> str: ...

    @abstractmethod
    def name(self) -> str: ...
```

### 8.2 Deep Agents (src/assistant/harnesses/deep_agents.py)

```python
from __future__ import annotations
from typing import Any
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from assistant.core.composition import compose_system_prompt
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.base import HarnessAdapter


class DeepAgentsHarness(HarnessAdapter):

    def name(self) -> str:
        return "deep_agents"

    async def create_agent(self, tools: list, extensions: list) -> Any:
        cfg = self.persona.harnesses.get("deep_agents", {})
        ext_tools = []
        for ext in extensions:
            ext_tools.extend(ext.as_langchain_tools())

        skills_dirs = ["./src/assistant/skills"]
        if self.role.skills_dir:
            skills_dirs.append(self.role.skills_dir)

        return create_deep_agent(
            model=init_chat_model(cfg.get("model", "anthropic:claude-sonnet-4-20250514")),
            tools=[*tools, *ext_tools],
            system_prompt=compose_system_prompt(self.persona, self.role),
            memory=cfg.get("memory_files", ["./AGENTS.md"]),
            skills=skills_dirs,
        )

    async def invoke(self, agent: Any, message: str) -> str:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": message}]}
        )
        for msg in reversed(result.get("messages", [])):
            if msg.get("role") == "assistant":
                return msg["content"]
        return ""

    async def spawn_sub_agent(self, sub_role, task, tools, extensions) -> str:
        sub = DeepAgentsHarness(self.persona, sub_role)
        agent = await sub.create_agent(tools, extensions)
        return await sub.invoke(agent, task)
```

### 8.3 MS Agent Framework (src/assistant/harnesses/ms_agent_fw.py)

```python
from __future__ import annotations
from typing import Any
from assistant.core.composition import compose_system_prompt
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.base import HarnessAdapter


class MSAgentFrameworkHarness(HarnessAdapter):

    def name(self) -> str:
        return "ms_agent_framework"

    async def create_agent(self, tools: list, extensions: list) -> Any:
        cfg = self.persona.harnesses.get("ms_agent_framework", {})
        if not cfg.get("enabled"):
            raise RuntimeError(
                f"MS Agent Framework not enabled for '{self.persona.name}'"
            )

        from agent_framework.claude import ClaudeChatClient
        client = ClaudeChatClient(model="claude-sonnet-4-20250514")
        agent = client.as_agent(
            name=f"assistant-{self.persona.name}-{self.role.name}",
            instructions=compose_system_prompt(self.persona, self.role),
        )
        for ext in extensions:
            for tool in ext.as_ms_agent_tools():
                agent.add_tool(tool)
        return agent

    async def invoke(self, agent: Any, message: str) -> str:
        return str(await agent.run(message))

    async def spawn_sub_agent(self, sub_role, task, tools, extensions) -> str:
        sub = MSAgentFrameworkHarness(self.persona, sub_role)
        agent = await sub.create_agent(tools, extensions)
        return await sub.invoke(agent, task)
```

### 8.4 Factory (src/assistant/harnesses/factory.py)

```python
from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig
from assistant.harnesses.base import HarnessAdapter
from assistant.harnesses.deep_agents import DeepAgentsHarness
from assistant.harnesses.ms_agent_fw import MSAgentFrameworkHarness

HARNESS_REGISTRY: dict[str, type[HarnessAdapter]] = {
    "deep_agents": DeepAgentsHarness,
    "ms_agent_framework": MSAgentFrameworkHarness,
}


def create_harness(
    persona: PersonaConfig, role: RoleConfig, harness_name: str,
) -> HarnessAdapter:
    if harness_name not in HARNESS_REGISTRY:
        raise ValueError(f"Unknown harness '{harness_name}'")
    cfg = persona.harnesses.get(harness_name, {})
    if not cfg.get("enabled", False):
        raise ValueError(
            f"Harness '{harness_name}' not enabled for '{persona.name}'"
        )
    return HARNESS_REGISTRY[harness_name](persona, role)
```

---

## Phase 9: Extension Protocol + Implementations

### 9.1 Protocol (src/assistant/extensions/base.py)

```python
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Extension(Protocol):
    name: str
    def as_langchain_tools(self) -> list[Any]: ...
    def as_ms_agent_tools(self) -> list[Any]: ...
    async def health_check(self) -> bool: ...
```

### 9.2 MS Graph (src/assistant/extensions/ms_graph.py)

```python
"""MS Graph extension — generic implementation (public repo).
Activated by persona config with tenant/scope specifics."""

from __future__ import annotations
from typing import Any


class MSGraphExtension:
    name = "ms_graph"

    def __init__(self, config: dict):
        self.scopes = config.get("scopes", [])

    def as_langchain_tools(self) -> list[Any]:
        # TODO: Wrap MS Graph operations as LangChain StructuredTools
        return []

    def as_ms_agent_tools(self) -> list[Any]:
        # TODO: Native MS Agent Framework AIFunction pattern
        return []

    async def health_check(self) -> bool:
        return True


def create_extension(config: dict) -> MSGraphExtension:
    return MSGraphExtension(config)
```

### 9.3 Gmail (src/assistant/extensions/gmail.py)

```python
"""Gmail extension — generic implementation (public repo)."""

from __future__ import annotations
from typing import Any


class GmailExtension:
    name = "gmail"

    def __init__(self, config: dict):
        self.scopes = config.get("scopes", [])

    def as_langchain_tools(self) -> list[Any]:
        return []

    def as_ms_agent_tools(self) -> list[Any]:
        return []

    async def health_check(self) -> bool:
        return True


def create_extension(config: dict) -> GmailExtension:
    return GmailExtension(config)
```

(Same pattern for teams.py, sharepoint.py, outlook.py, gcal.py, gdrive.py)

---

## Phase 10: Delegation

### 10.1 Spawner (src/assistant/delegation/spawner.py)

```python
"""Sub-agent delegation with role switching."""

from __future__ import annotations

import asyncio

from assistant.core.persona import PersonaConfig
from assistant.core.role import RoleConfig, RoleRegistry
from assistant.harnesses.base import HarnessAdapter


class DelegationSpawner:

    def __init__(
        self, persona: PersonaConfig, parent_role: RoleConfig,
        harness: HarnessAdapter, tools: list, extensions: list,
    ):
        self.persona = persona
        self.parent_role = parent_role
        self.harness = harness
        self.tools = tools
        self.extensions = extensions
        self.role_registry = RoleRegistry()
        self._active: int = 0

    async def delegate(self, sub_role_name: str, task: str) -> str:
        allowed = self.parent_role.delegation.get("allowed_sub_roles", [])
        if sub_role_name not in allowed:
            raise ValueError(
                f"'{self.parent_role.name}' cannot delegate to "
                f"'{sub_role_name}'. Allowed: {allowed}"
            )
        max_c = self.parent_role.delegation.get("max_concurrent", 3)
        if self._active >= max_c:
            raise RuntimeError(f"Max concurrent ({max_c}) reached.")

        available = self.role_registry.available_for_persona(self.persona)
        if sub_role_name not in available:
            raise ValueError(
                f"Role '{sub_role_name}' not available for '{self.persona.name}'"
            )

        sub_role = self.role_registry.load(sub_role_name, self.persona)
        self._active += 1
        try:
            return await self.harness.spawn_sub_agent(
                sub_role, task, self.tools, self.extensions,
            )
        finally:
            self._active -= 1

    async def delegate_parallel(
        self, delegations: list[tuple[str, str]],
    ) -> list[str]:
        return await asyncio.gather(
            *(self.delegate(r, t) for r, t in delegations)
        )
```

---

## Phase 11: CLI

```python
"""CLI — persona × role × harness selection."""

import asyncio
import click

from assistant.core.persona import PersonaRegistry
from assistant.core.role import RoleRegistry
from assistant.core.http_tools.discovery import discover_tools
from assistant.harnesses.factory import create_harness


@click.command()
@click.option("--persona", "-p", type=str, required=True)
@click.option("--role", "-r", type=str, default=None)
@click.option("--harness", "-h",
              type=click.Choice(["deep_agents", "ms_agent_framework"]),
              default="deep_agents")
@click.option("--list-personas", is_flag=True)
@click.option("--list-roles", is_flag=True)
def main(persona, role, harness, list_personas, list_roles):
    """Start the agentic-assistant."""
    persona_reg = PersonaRegistry()
    role_reg = RoleRegistry()

    if list_personas:
        click.echo("Available personas (initialized submodules):")
        for p in persona_reg.discover():
            click.echo(f"  {p}")
        return

    if list_roles:
        pc = persona_reg.load(persona)
        click.echo(f"Roles for {pc.display_name}:")
        for r in role_reg.available_for_persona(pc):
            click.echo(f"  {r}")
        return

    asyncio.run(_run(persona_reg, role_reg, persona, role, harness))


async def _run(persona_reg, role_reg, persona_name, role_name, harness_name):
    pc = persona_reg.load(persona_name)
    if not role_name:
        role_name = pc.default_role
    rc = role_reg.load(role_name, pc)

    click.echo(f"Persona:  {pc.display_name}")
    click.echo(f"Role:     {rc.display_name}")
    click.echo(f"Harness:  {harness_name}")

    # Discover HTTP tools
    all_tools = []
    for src_name, src_cfg in pc.tool_sources.items():
        if src_cfg["base_url"]:
            try:
                tools = await discover_tools(
                    base_url=src_cfg["base_url"],
                    auth_headers=(
                        {"Authorization": src_cfg["auth_header"]}
                        if src_cfg["auth_header"] else None
                    ),
                    allowed_tools=src_cfg["allowed_tools"] or None,
                )
                all_tools.extend(tools)
                click.echo(f"  Tools:  {len(tools)} from {src_name}")
            except Exception as e:
                click.echo(f"  Warning: {src_name}: {e}")

    # Load extensions (private-first, then public fallback)
    extensions = persona_reg.load_extensions(pc)
    click.echo(f"  Extensions: {len(extensions)}")

    adapter = create_harness(pc, rc, harness_name)
    agent = await adapter.create_agent(all_tools, extensions)

    click.echo(f"\nReady. Commands: /roles /role <n> /delegate <role> <task> quit\n")

    while True:
        user_input = click.prompt("You", prompt_suffix="> ")
        if user_input.lower() in ("quit", "exit"):
            break

        if user_input == "/roles":
            for r in role_reg.available_for_persona(pc):
                marker = " ←" if r == rc.name else ""
                click.echo(f"  {r}{marker}")
            continue

        if user_input.startswith("/role "):
            new_role = user_input.split(" ", 1)[1].strip()
            try:
                rc = role_reg.load(new_role, pc)
                adapter = create_harness(pc, rc, harness_name)
                agent = await adapter.create_agent(all_tools, extensions)
                click.echo(f"→ {rc.display_name}\n")
            except ValueError as e:
                click.echo(f"Error: {e}\n")
            continue

        if user_input.startswith("/delegate "):
            parts = user_input.split(" ", 2)
            if len(parts) < 3:
                click.echo("Usage: /delegate <role> <task>\n")
                continue
            from assistant.delegation.spawner import DelegationSpawner
            spawner = DelegationSpawner(pc, rc, adapter, all_tools, extensions)
            try:
                result = await spawner.delegate(parts[1], parts[2])
                click.echo(f"\n[{parts[1]}]> {result}\n")
            except (ValueError, RuntimeError) as e:
                click.echo(f"Error: {e}\n")
            continue

        response = await adapter.invoke(agent, user_input)
        click.echo(f"\n[{rc.display_name}]> {response}\n")


if __name__ == "__main__":
    main()
```

Usage:
```bash
# Work persona, default role, Deep Agents
uv run python -m assistant.cli -p work

# Work persona, researcher role
uv run python -m assistant.cli -p work -r researcher

# Work persona, MS Agent Framework harness
uv run python -m assistant.cli -p work -h ms_agent_framework

# Personal persona
uv run python -m assistant.cli -p personal -r researcher

# List initialized personas
uv run python -m assistant.cli --list-personas

# List roles for work
uv run python -m assistant.cli -p work --list-roles
```

---

## Phase 12: CLAUDE.md (Public Repo)

```markdown
# agentic-assistant

Personal AI assistant with plugin-based persona system and composable roles.

## Repo Structure
- **Public repo**: code, roles, extension implementations, CLI
- **Private config repos**: mounted as git submodules in `personas/`
- Each persona (work, personal) is a separate private repo

## Key Concepts
- **Persona** = execution boundary (DB, auth, tools) — private config
- **Role** = behavioral pattern (prompt, workflow, delegation) — public base
- Persona × Role compose via three-layer prompt system
- Sub-agents inherit persona, switch role

## Setup
```bash
# Clone public repo
git clone https://github.com/jankneumann/agentic-assistant.git

# Initialize persona submodules you need
git submodule update --init personas/work      # needs Comcast GH Enterprise access
git submodule update --init personas/personal  # needs GitHub private repo access

# Install dependencies
uv sync
```

## Directory Layout
- `roles/` — Shared role definitions (public, reusable)
- `personas/` — Submodule mount points for private config repos
- `personas/_template/` — Template for creating new personas (public)
- `src/assistant/core/` — Harness-agnostic library (public)
- `src/assistant/harnesses/` — Harness adapters (public)
- `src/assistant/extensions/` — Extension implementations (public)
- `src/assistant/delegation/` — Sub-agent spawning (public)

## Adding a New Persona
1. Create a new private repo from template:
   `./scripts/init-persona-repo.sh /tmp/my-config`
2. Push to your private Git host
3. Mount: `./scripts/setup-persona.sh myname https://git.example.com/my-config`

## Adding a New Role
1. `cp -r roles/_template roles/newrole`
2. Edit `roles/newrole/role.yaml` and `prompt.md`
3. Add persona overrides in private repos: `roles/newrole.yaml`

## Backend Services
HTTP APIs with progressive discovery via `/help`. Use HTTP for all
inter-service calls.

## Conventions
- Python 3.12, type hints, Ruff, pytest
- Extension code in public repo, activation config in private repos
- Each persona has its own separate database (ParadeDB Postgres)
```

---

## Phase 13: AGENTS.md (Public Repo)

```markdown
# Personal Assistant Memory

## Identity
- Owner: Jan Kneumann
- Role: Strategy Lead, AI and Data at Comcast Cable

## Architecture
- Public code repo + private persona config repos (git submodules)
- Persona × Role composition system
- Separate ParadeDB Postgres per persona
- Separate Graphiti knowledge graph per persona
- Backend services via HTTP: agentic-coding-tools, agentic-content-analyzer
- Harnesses: Deep Agents, MS Agent Framework, Claude Code, Codex

## Personas
- **work**: MS ecosystem, Comcast context, leadership-facing
- **personal**: Google ecosystem, exploratory

## Roles
- **chief_of_staff**: triage, briefings, delegation (default)
- **researcher**: deep research with source synthesis
- **planner**: strategic planning, roadmaps
- **writer**: content drafting calibrated to audience
- **coder**: code analysis, implementation, repo ops

## Preferences
- Direct, substantive communication
- Architectural thinking
- Open-source where feasible
- Python/TypeScript, ParadeDB, Railway

## Learned Patterns
<!-- Agent appends here -->
```

---

## Phase 14: Environment Configuration

### .env.example

```bash
# ── Work Persona ──
WORK_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/assistant_work
WORK_GRAPHITI_URL=redis://localhost:6379/0
WORK_MS_TENANT_ID=
WORK_MS_CLIENT_ID=
WORK_MS_CLIENT_SECRET=
WORK_FOUNDRY_ENDPOINT=

# ── Personal Persona ──
PERSONAL_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5433/assistant_personal
PERSONAL_GRAPHITI_URL=redis://localhost:6379/1
PERSONAL_GOOGLE_CLIENT_ID=
PERSONAL_GOOGLE_CLIENT_SECRET=
PERSONAL_GOOGLE_REFRESH_TOKEN=

# ── Backend Services ──
CONTENT_ANALYZER_URL=http://localhost:8100
CONTENT_ANALYZER_AUTH=
CODING_TOOLS_URL=http://localhost:8200
CODING_TOOLS_AUTH=

# ── Model ──
ANTHROPIC_API_KEY=
```

---

## Phase 15: Validation Checklist

### Multi-Repo Setup
- [ ] Public repo clones without errors (no private dependencies)
- [ ] `--list-personas` shows only initialized submodules
- [ ] Uninitialized submodule gives helpful error with init command
- [ ] `git submodule update --init personas/work` mounts work config
- [ ] `git submodule update --init personas/personal` mounts personal config
- [ ] `scripts/init-persona-repo.sh` creates valid config from template
- [ ] `scripts/setup-persona.sh` mounts a private repo as submodule

### Persona Isolation
- [ ] Work persona connects to work DB only
- [ ] Personal persona connects to personal DB only
- [ ] Work extensions load (private-first, then public fallback)
- [ ] Personal extensions load
- [ ] Extension health checks pass

### Role System
- [ ] `--list-roles` shows all roles for a persona
- [ ] Role overrides from private config merge correctly
- [ ] Work + researcher prompt includes private override content
- [ ] Personal + researcher prompt includes different override
- [ ] Adding a new role directory makes it discoverable

### Composition
- [ ] System prompt has three layers (base → persona → role)
- [ ] Active context summary is correct

### Harnesses
- [ ] Deep Agents adapter creates and responds
- [ ] MS Agent Framework adapter creates and responds (work only)
- [ ] MS Agent Framework correctly refuses for personal persona

### Delegation
- [ ] `/delegate researcher <task>` spawns sub-agent
- [ ] Disallowed delegation raises clear error
- [ ] Max concurrent enforced
- [ ] `/role researcher` switches mid-session

### Memory
- [ ] Changes to personas/work/memory.md can be committed to private repo
- [ ] `git log` in private repo shows memory evolution over time
- [ ] Claude Code / Codex can operate via CLAUDE.md

---

## Phase 16: Future Iterations (Do Not Implement Now)

- **Cross-persona bridge** — Controlled insight transfer with approval
- **A2A protocol** — MS Agent Framework inter-agent communication
- **Harness auto-routing** — Auto-select harness by task type
- **Multi-model routing** — Lighter models for routing
- **Proactive monitoring** — Watch content-analyzer, surface items
- **MCP server exposure** — Expose assistant as MCP server
- **NotebookLM integration** — Audio briefings
- **Railway deployment** — Run persona instances as services
- **Role learning** — Agent proposes new roles from usage patterns
- **Delegation analytics** — Track effective delegation patterns
- **Persona config encryption** — Encrypt sensitive fields in private repos
  for additional security layer beyond repo access control
