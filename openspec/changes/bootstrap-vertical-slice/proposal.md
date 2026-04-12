# Proposal: bootstrap-vertical-slice

## Why

This repo is an empty scaffold. The `docs/agentic-assistant-bootstrap-v4.1.md` spec
describes a 15-phase design, but landing all of it in one change would ship a
large surface area where most modules are `# TODO` stubs — making review nearly
worthless and creating a long window of broken-state commits.

A vertical slice delivers an end-to-end working skeleton (you can run
`uv run assistant -p personal -r chief_of_staff` and get a response) using the
**smallest** surface area that exercises every architectural seam that later
proposals will extend: persona discovery, role composition, harness dispatch,
extension loading, delegation, and CLI. Later proposals can then add real
functionality (HTTP tools, DB, Google/MS integrations) to proven seams rather
than designing-and-implementing both at once.

## What Changes

Adds the following capabilities (all ADD, no prior specs exist):

- **persona-registry** — discovers `personas/<name>/persona.yaml` files in
  submodule-mounted directories, loads into typed `PersonaConfig`, resolves
  env-var references for secrets, surfaces helpful errors when a submodule is
  not initialized.
- **role-registry** — loads public role definitions from `roles/<name>/` and
  merges in private overrides from `personas/<persona>/roles/<role>.yaml`
  (prompt append, additional preferred tools, delegation overrides, context
  overrides).
- **prompt-composition** — three-layer system prompt: base prompt → persona
  prompt augmentation → role prompt (+ active configuration summary).
- **harness-adapter** — abstract `HarnessAdapter` base, concrete
  `DeepAgentsHarness` implementation, factory with registry. MS Agent Framework
  registered but raises `NotImplementedError` (will be filled in P5).
- **extension-registry** — `Extension` Protocol + generic stub implementations
  for `ms_graph`, `teams`, `sharepoint`, `outlook`, `gmail`, `gcal`, `gdrive`
  (all return empty tool lists; real impls in P4/P5). Private-first loader that
  falls back to public extensions.
- **delegation-spawner** — `DelegationSpawner` enforcing
  `parent_role.delegation.allowed_sub_roles` and `max_concurrent`, spawning
  sub-agents via the current harness with role switching.
- **cli-interface** — `assistant` entry point with `-p/--persona`, `-r/--role`,
  `-h/--harness`, `--list-personas`, `--list-roles`, in-session `/role <name>`,
  `/delegate <role> <task>`, and a plain interactive REPL.

Also lands supporting assets (tracked here, not as specs):

- `pyproject.toml` with pinned deps; `uv.lock`.
- `roles/_template/`, plus real `researcher`, `planner`, `chief_of_staff`,
  `writer`, `coder` role directories (role.yaml + prompt.md + skill files).
- `personas/_template/` in the public repo.
- Populated `personas/personal/` submodule content (persona.yaml, prompt.md,
  memory.md, tools.yaml, roles/) — committed to the private submodule repo.
- `scripts/setup-persona.sh`, `scripts/init-persona-repo.sh`.
- `CLAUDE.md`, `AGENTS.md`, updated `README.md`, `.env.example`.
- `tests/` for all seven capabilities above.
- `.github/workflows/ci.yml` (lint + type-check + test).

## Approaches Considered

### Approach A: Ship the entire v4.1 spec in one change — Effort: L

**Description**: Follow the bootstrap spec end-to-end — core + both harnesses
+ all seven extensions + HTTP tools + DB layer + delegation + CLI + tests.

- **Pros**: Matches the shape of the source document; no roadmap juggling.
- **Cons**: ~40 new files, most of which are TODO-stubbed; no review signal
  because reviewers can't meaningfully evaluate placeholder code; the first
  working `assistant` CLI invocation sits behind ~3× the necessary implementation
  work; regressions in one subsystem block the whole PR.

### Approach B (Recommended): Thin vertical slice, then sequenced follow-ons — Effort: M

**Description**: Land a minimal end-to-end slice that boots and responds
(core + Deep Agents + CLI + stubs + delegation + tests + CI). Every other
capability (HTTP tools, DB, Google extensions, MS extensions, work persona,
etc.) becomes its own proposal in `openspec/roadmap.md`.

- **Pros**: First PR is small enough to review seriously; every later proposal
  extends a *working* seam rather than a TODO-stubbed one; implementation
  feedback informs later designs (e.g., whether `ExtensionConfig` really needs
  a `config` dict); each proposal is independently testable.
- **Cons**: More PR overhead; risk of scope drift between proposals if the
  vertical slice's interfaces turn out to be wrong (mitigated by choosing
  interfaces directly from the v4.1 spec, which has been iterated).

### Approach C: Core-only first, everything else next — Effort: S

**Description**: Even thinner slice — just `persona.py`, `role.py`,
`composition.py`, and a script that prints a composed prompt. No harness, no
CLI, no extensions.

- **Pros**: Smallest possible first PR.
- **Cons**: Nothing runs end-to-end, so the interfaces haven't been exercised;
  the next proposal would have to make large changes to accommodate harness/CLI
  needs discovered late. Proves less.

### Selected Approach: **B — Thin vertical slice**

Chosen because it gets to a working `assistant` CLI in one change while still
keeping the PR small enough to review line-by-line. Unselected approaches:

- **A** rejected: most content would be TODO stubs, making review theater.
- **C** rejected: doesn't exercise harness/CLI/extension seams, so follow-on
  proposals would likely force redesign of core interfaces.

## Impact

- Affected specs: **new** — `persona-registry`, `role-registry`,
  `prompt-composition`, `harness-adapter`, `extension-registry`,
  `delegation-spawner`, `cli-interface`.
- Affected code: all new (`src/assistant/`, `tests/`, `roles/`, `personas/_template/`,
  `scripts/`, `.github/workflows/`).
- Submodule side-effect: populates `personas/personal/` with initial content
  committed+pushed to the private origin (`agentic-assistant-config-personal`).
- No breaking changes — greenfield repo.

## Out of Scope (deferred to roadmap)

- HTTP tools layer (`src/assistant/core/http_tools/`) → **P2**
- Per-persona Postgres/Graphiti/memory layer (`src/assistant/core/db.py`, etc.) → **P3**
- Real Google extensions (Gmail, GCal, GDrive) → **P4**
- Real MS extensions (MS Graph, Teams, SharePoint, Outlook) + full MS Agent
  Framework harness → **P5**
- Work persona submodule wiring → **P6**
- Advanced delegation (`delegate_parallel`, monitoring) → **P8**
- MCP server exposure → **P9**
- Railway deployment → **P10**
