# Proposal: add-teacher-role

## Why

Jan wants to master topics well enough to teach them to others. Two of the
most effective structured teaching methods — the **Feynman technique**
(explain-check-re-teach loop toward a one-sentence definition) and the
**Socratic method** (question-driven surfacing of assumptions) — are both
pure *interaction patterns*: they dictate a turn-taking structure with the
user, nothing else. They don't need a separate tool backend or persona;
they need a behavioral contract the agent can follow.

Today the repo has five roles (`chief_of_staff`, `coder`, `planner`,
`researcher`, `writer`), none of which encode a teaching loop. Running
Feynman or Socratic today means manually pasting the mega-prompt into a
generic session each time, losing the benefits of composable persona
config, delegation to `researcher` for fact-checking, and skill-level
knowledge-base access once the HTTP tool layer (P3) lands.

A natural home exists: a `teacher` role under `roles/teacher/`, with each
method as a markdown **skill** under `roles/teacher/skills/`. This fits
the repo's existing split between roles (behavioral pattern) and skills
(knowledge artifacts the role loads on demand), and it reuses Deep
Agents' native skill-discovery mechanism — no new core plumbing required.

## What Changes

1. **New `teacher` role** at `roles/teacher/` (`role.yaml` + `prompt.md`).
   The role's prompt defines its meta-behavior: on first turn, offer the
   user a choice between available methods (unless one was specified via
   CLI flag or REPL command); during the learning loop, honor mid-session
   method switches cleanly; summarize progress before switching.

2. **Two initial skill files** at `roles/teacher/skills/`:
   - `feynman.md` — the explain→check→diagnose→re-teach loop the user
     provided, adapted to the repo's voice.
   - `socratic.md` — question-only loop that surfaces the user's existing
     model of the topic before guiding them to fill gaps.
   Additional methods (ELI5, analogy-ladder, teach-back, spaced recall)
   are explicitly out of scope for this change and tracked as a
   follow-on proposal.

3. **Delegation to `researcher`**. Teacher's `role.yaml` declares
   `delegation.allowed_sub_roles: [researcher]`. When the user asks the
   teacher to verify a concept or the teacher flags its own uncertainty,
   it may spawn a `researcher` sub-agent to fact-check before teaching.
   This is the only sub-role — teacher does not delegate to `writer`,
   `coder`, etc.

4. **Declarative tool preference**. Teacher's `role.yaml` lists
   `content_analyzer:search` and `content_analyzer:knowledge_graph` in
   `preferred_tools`. These are not wired to real tools until P3
   (`http-tools-layer`) — today they only flow into the composed system
   prompt via `composition.py:49-52`. Each skill's markdown specifies
   *when* in its loop the tools become useful (e.g. Feynman Step 1:
   "before writing your plain-language explanation, you MAY consult
   `knowledge_graph` for the canonical definition of the target
   concept; cite it as an anchor").

5. **CLI surface additions** (`src/assistant/cli.py`):
   - New `--method <name>` / `-m <name>` option on the top-level command,
     valid only when `--role teacher` is active; passes the chosen
     method as a first-turn directive to the agent.
   - New `/method <name>` REPL command, which injects a directive into
     the conversation to switch methods without rebuilding the agent
     (unlike `/role`, which destroys the current agent state — see
     `cli.py:146-159`).
   - New `/methods` REPL command, lists the skill files under
     `roles/teacher/skills/` and marks the currently-active one.

6. **Tests** (`tests/test_role_registry.py`, `tests/test_cli.py`): the
   teacher role is discovered; its `preferred_tools` and
   `allowed_sub_roles` match the declared values; `--method` parsing and
   `/method` / `/methods` REPL branches behave correctly; `--method`
   without `--role teacher` raises a `UsageError`.

7. **Roadmap registration**. Add `add-teacher-role` as a non-phase item
   in `openspec/roadmap.md` and `openspec/roadmap.yaml` so this work is
   visible in the DAG without implying it blocks any P-phase.

## Approaches Considered

### Approach 1: One `teacher` role with per-method skill files *(Recommended)*

**Description**: Single `roles/teacher/` directory. Each teaching method
is a `.md` file under `roles/teacher/skills/`. The role's `prompt.md`
contains meta-behavior (method-negotiation, mid-session switching,
completion signaling). Deep Agents' native `skills=` parameter makes
the files discoverable; the model self-selects based on user intent or
explicit `/method` directive.

**Pros**:
- One role, one set of shared behavioral rules (never re-teach what I
  already demonstrated I know; flag analogies as analogies; honor the
  completion signal).
- In-conversation method switching preserves agent state — no agent
  rebuild, no loss of dialog history. Critical for a multi-turn learning
  loop.
- Adding a new method = one markdown file. No new role, no new entry in
  role registry, no new delegation graph.
- `preferred_tools` declared once at role level; each skill narrates
  *when* to reach for them, so the model's tool-reaching is contextual
  to the active method.

**Cons**:
- Method selection today is model-driven (the agent decides which skill
  to load based on the system prompt's instructions). If the model
  picks the wrong skill, there's no hard gate. Mitigated by the
  `/method` REPL command and `--method` flag for deterministic
  selection.
- The tool-gating is advisory, not enforced: the Feynman skill can
  *tell* the model not to reach for `knowledge_graph` outside Step 1,
  but nothing prevents it. If this becomes a real problem after P3 wires
  actual tools, we introduce per-skill tool manifests in a follow-on.

**Effort**: S

### Approach 2: One role per method (`teacher_feynman`, `teacher_socratic`)

**Description**: Two sibling roles under `roles/`. Each has its own
complete `role.yaml` + `prompt.md`. Switching methods mid-session uses
the existing `/role` command.

**Pros**:
- Hard, explicit selection: `assistant -r teacher_feynman` is
  unambiguous; no model-driven dispatch.
- Per-role `preferred_tools` and `delegation` trivially differ between
  methods if we later want that.

**Cons**:
- **Agent-state loss on method switch**: `cli.py:146-159` rebuilds the
  adapter + agent on `/role <name>`. A Feynman loop mid-way would
  restart from an empty conversation if the user switches to Socratic.
  That breaks the entire teaching-loop premise.
- Shared behavioral rules (analogy flagging, completion signal,
  no-re-teaching) get duplicated across N `prompt.md` files. Every new
  method is a full role setup.
- Adds N rows to every `/roles` listing, cluttering the role picker
  with what are really variations of one behavioral family.

**Effort**: S (same N files, but more ceremony per file)

### Approach 3: Parameterize an existing role (e.g. extend `researcher`)

**Description**: Add a `teaching_mode: feynman|socratic|null` field to
the existing `researcher` role's override machinery, gated by the
persona config. Teacher behavior becomes a mode of researcher.

**Pros**:
- No new role directory at all.

**Cons**:
- Category error. Researcher's job is *source-grounded analysis for
  me*; teacher's job is *drive a turn-taking loop with me toward my
  own mastery*. Different audiences, different success signals,
  different completion conditions. Conflating them makes both
  prompts harder to reason about.
- `role.yaml` has no "modes" concept today; introducing one adds
  architectural surface for a single use case.

**Effort**: M (core schema change for marginal benefit)

## Selected Approach

**Approach 1** — one `teacher` role with per-method skill files.

Approach 2 is disqualified by the agent-rebuild issue alone: a teaching
loop that can't survive a method switch defeats the primary motivation
(a coach that adapts its technique mid-session as needed).

Approach 3 conflates two different behavioral roles and would require
a core schema change for no real gain.

Approach 1 reuses existing repo machinery end-to-end (role directories,
Deep Agents skill discovery, `preferred_tools` declaration, delegation
graph) and lands the two initial methods plus CLI surface in under a
dozen files.

## Out of Scope

- **Additional methods** beyond Feynman and Socratic. ELI5, analogy
  ladder, teach-back, and spaced recall are tracked for a future
  proposal. Adding them is a single-file-per-method change once this
  proposal ships.
- **Per-skill tool gating** (capability activation bound to skill
  selection). This is a genuine architectural extension to the
  harness's tool-binding model. Today and through P3, tool access is
  declared at the role level and narrated at the skill level; hard
  per-skill gates are a P3-or-later proposal contingent on whether the
  narrated contract proves insufficient in practice.
- **Real content-analyzer tool access**. Gated on P3 `http-tools-layer`.
  `preferred_tools` on the teacher role is forward-declared.
- **Persona-specific teacher overrides**. No
  `personas/<name>/roles/teacher.yaml` in this change. Can be added
  per-persona if the `personal` persona wants a tone tweak.
- **Evaluation harness for teaching effectiveness**. No automated
  scoring of whether a Feynman loop actually produced mastery. That's
  a research problem unto itself.
