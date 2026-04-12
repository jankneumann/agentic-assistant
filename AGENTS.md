# Personal Assistant Memory

## Identity
- Owner: Jan Kneumann
- Role: Strategy Lead, AI and Data at Comcast Cable

## Architecture
- Public code repo + private persona config repos (git submodules)
- Persona × Role composition system
- Separate ParadeDB Postgres per persona (wired in P3)
- Separate Graphiti knowledge graph per persona (wired in P3)
- Backend services via HTTP: agentic-coding-tools, agentic-content-analyzer (wired in P2)
- Harnesses: Deep Agents (implemented), MS Agent Framework (stub until P5),
  Claude Code, Codex

## Personas
- **personal**: Google ecosystem (Gmail, GCal, GDrive), exploratory tone
- **work**: MS ecosystem (MS Graph, Teams, SharePoint, Outlook), Comcast
  context, leadership-facing (mounted only on work machine — P6)

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
