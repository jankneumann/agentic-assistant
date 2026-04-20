# Design: add-teacher-role

## Context

The agentic-assistant repo has a two-layer behavioral contract:

- **Roles** (`roles/<name>/role.yaml` + `prompt.md`) describe *how* an
  agent interacts — delegation graph, planning defaults, tool
  preferences, output shape. They flow through
  `composition.compose_system_prompt()` into the agent's system prompt.
- **Skills** (`roles/<name>/skills/*.md`) are knowledge artifacts
  passed to `create_deep_agent(skills=...)`. Deep Agents lets the
  model inspect these and decide when to apply one.

This change adds a `teacher` role whose behavior is "drive a
structured teaching loop with the user toward mastery of a topic".
Each *method* (Feynman, Socratic) is a skill: a loop definition the
model loads when the method is active.

The central design tension is that a teaching loop is stateful
(Step 1 → user attempt → gap diagnosis → repeat until score ≥ 9), and
must survive method switches without losing that state. This rules out
approaches where switching method destroys the agent.

## Goals

- **G1**: Make Feynman and Socratic methods available as first-class
  behaviors selectable at startup (`--method`) or mid-session
  (`/method`).
- **G2**: Let the teacher delegate to `researcher` to fact-check a
  concept before teaching it, without the teacher having to re-
  implement research workflow.
- **G3**: Preserve conversation state across method switches.
- **G4**: Forward-declare KB tool access (`content_analyzer:search`,
  `content_analyzer:knowledge_graph`) so the teacher role
  "just works" once P3 (`http-tools-layer`) wires real tools.
- **G5**: Keep the change scoped — two methods, no new core
  abstractions, no speculative per-skill tool gating.

## Non-goals

- **NG1**: Enforce per-skill tool permissions. Today's `preferred_tools`
  is advisory (`composition.py:49-52` renders it into the prompt; no
  runtime gate). This proposal does not change that. If post-P3
  observation shows the model reaching for `knowledge_graph` in a
  Socratic dialog when it shouldn't, that's the signal for a follow-on
  proposal to add per-skill manifests.
- **NG2**: Ship more than two methods. ELI5, analogy-ladder, teach-back,
  spaced-recall, etc. are explicitly deferred.
- **NG3**: Rewrite `/role` to preserve conversation state. That's a
  separate latent bug / design question about the REPL; this change
  routes around it by using `/method` (which does NOT rebuild the
  agent) for within-teacher switches.
- **NG4**: Add a persona override of teacher in `personas/personal/`.
  The base role's prompt is persona-agnostic by design.

## Key decisions

### D1: Single `teacher` role, methods as skills

See Approach 1 in `proposal.md`. The decisive factor is that Deep
Agents' skill mechanism is already in place and designed for exactly
this — the model sees a directory of capability descriptions and picks
one based on context or explicit instruction. We piggyback on it.

### D2: No default method when unspecified — teacher offers a choice

When a session starts with `--role teacher` and no `--method`, the
teacher's first turn MUST present the user with the available methods
and ask them to pick one. Rationale:

- Matches the user's preference (resolved 2026-04-16): "pick one from
  options" — the teacher presents options, the user selects.
- Avoids silently biasing the session toward one method. Feynman suits
  concept mastery; Socratic suits clarifying the user's existing model.
  Picking for the user is a judgment call the user should make.
- Keeps the behavior symmetric whether the method is specified
  upstream (via `--method` or `/method`) or selected in-band.

### D3: CLI and REPL surface

Two parallel entry points, same semantics downstream:

- **`--method <name>` / `-m <name>`** on `assistant`. Valid only when
  `--role teacher` (or `teacher` is the persona's `default_role`).
  Specifying `--method` with any other role raises `click.UsageError`.
- **`/method <name>`** inside the REPL. Valid only when the current
  role is `teacher`. Injects a system-level directive into the next
  turn: *"From this turn forward, use the `<name>` method. Summarize
  where we are in the current method's loop, then re-enter Step 1 of
  the new method."*
- **`/methods`** inside the REPL. Lists skills under
  `roles/teacher/skills/` with the active method marked, analogous to
  `/roles`.

The key asymmetry with `/role <name>` (which rebuilds the agent and
loses history — `cli.py:146-159`) is that `/method` stays within the
same agent instance. It's a prompt-level, not harness-level, switch.

### D4: Method resolution precedence

When the teacher role activates, the active method is resolved in this
order:

1. `--method <name>` if provided on the command line.
2. `/method <name>` if issued in the REPL (overrides #1 for subsequent
   turns).
3. None — the teacher's first turn asks the user to choose from the
   skills under `roles/teacher/skills/`.

The REPL records the active method name and displays it in the prompt
prefix (e.g. `[Teacher:feynman]>` instead of the generic
`[Teacher]>`). This gives the user visible feedback that a switch took
effect.

### D5: Delegation scope — researcher only

`teacher/role.yaml` declares
`delegation.allowed_sub_roles: [researcher]`. Rationale:

- **Verification**: teacher may need to check a concept's canonical
  definition before teaching it. Researcher's existing
  knowledge-graph-first workflow fits this exactly.
- **Not writer**: teacher doesn't draft content *for* the user; it
  draws content *out of* the user.
- **Not coder**: if the topic is code, the user explains code; the
  teacher doesn't go author demos.
- **Not planner / chief_of_staff**: no cross-role planning or
  orchestration responsibilities.

`max_concurrent: 1` — the teacher is a conversation, not a batch
dispatcher. Parallel research sub-agents would fracture the loop's
turn-taking.

### D6: Tool declaration at role level, timing-guidance at skill level

`teacher/role.yaml`:
```yaml
preferred_tools:
  - content_analyzer:search
  - content_analyzer:knowledge_graph
```

These are **forward declarations**. `composition.py:49-52` folds them
into the system prompt. Real wiring lands with P3.

Each skill's markdown specifies *when* to reach for the declared
tools. Example from `feynman.md`:

> Before Step 1, you MAY (not MUST) query
> `content_analyzer:knowledge_graph` for the canonical definition of
> the target concept. If you do, cite it verbatim as the anchor the
> user's explanation will be checked against. Do NOT consult it
> between steps — the point of Feynman is to surface the user's model,
> not re-teach from an external source.

This is narrated tool-gating: the contract is in the prompt, not in
the harness. See NG1 for the explicit decision to defer runtime
enforcement.

### D7: Skill-switch transition protocol

When the user issues `/method <name>` or asks "let's try Socratic
instead", the teacher's prompt instructs it to:

1. Complete the current response turn normally (don't abandon
   mid-explanation).
2. Produce a ≤3-sentence summary of "where we are" in the current
   method's loop: what has been explained, what the user has
   demonstrated mastery of, what gaps remain.
3. Announce the switch: *"Switching to `<new>` method."*
4. Enter Step 1 of the new method, preserving the identified
   remaining-gaps as the new loop's starting focus.

This preserves the teaching arc across the switch — it doesn't reset
to zero — while keeping the state-handoff inside the model's
conversational memory rather than in external structure.

### D8: Completion contract per method

Each skill defines its own completion signal. Feynman: user scores 9+
on a gap-diagnosis round without hints, at which point the teacher
emits `"You've got it. Here's the one-sentence definition you could
use to teach someone else: ..."`. Socratic: the user can answer their
own question about the topic without leading, at which point the
teacher emits `"You're teaching yourself now. Here's the frame you'd
use to open this for someone else: ..."`.

Both signals are plain-text, not structured — the REPL doesn't need
to detect them. They exist so the user recognizes session closure.

### D9: Non-registration with `personas/personal/roles/`

No `personas/personal/roles/teacher.yaml` in this change. The
teacher's behavior doesn't vary by persona (teaching a personal topic
vs. a work topic doesn't change the loop structure). Persona overrides
can be added later if tone-shaping proves useful.

## Test strategy

- **Unit**: `tests/test_role_registry.py` gains a test case that
  discovers `teacher`, loads it, and asserts:
  - `preferred_tools` contains both `content_analyzer:*` entries.
  - `delegation.allowed_sub_roles == ["researcher"]`.
  - `delegation.max_concurrent == 1`.
  - `skills_dir` resolves to `./roles/teacher/skills`.
  - The prompt contains the meta-behavior markers ("offer the user a
    choice", "summarize before switching").
- **CLI**: `tests/test_cli.py` gains cases for:
  - `--method feynman` with `--role teacher` accepted.
  - `--method feynman` with `--role coder` raises `UsageError`
    mentioning that `--method` requires `--role teacher`.
  - `/methods` REPL branch lists skill files with active marker.
  - `/method <name>` REPL branch accepts a valid skill name and
    rejects an invalid one without crashing the REPL.
- **Integration**: no end-to-end "did the loop produce mastery" test —
  out of scope (NG-evaluation-harness).
- **Fixture**: no changes to `tests/fixtures/personas/` — teacher is a
  public role and its tests run against the real `roles/teacher/`.

## Risks

- **R1**: Model picks the wrong skill at first-turn. Mitigation: the
  teacher's prompt explicitly asks the user to pick when method is
  unspecified, rather than selecting.
- **R2**: Model reaches for `content_analyzer:*` tools mid-Feynman
  (i.e. outside Step 1), violating the narrated contract. Currently
  unobservable — tools aren't wired until P3. Flagged for the post-P3
  review: if it happens in practice, the follow-on proposal for
  per-skill tool gating becomes concrete.
- **R3**: Deep Agents' skill-discovery picks up stale skills after a
  file is deleted or renamed. Low-impact — skills are read at agent
  creation time, so a REPL session already loaded keeps the skill set
  it started with. A fresh session picks up changes.
- **R4**: The `/method` REPL command's prompt-level directive is
  ignored by the model. Low-likelihood given system-level injection,
  but user can always exit and restart with `--method` as a fallback.

## References

- Option-B discussion (2026-04-16 session): settled on single-role +
  method-skills, researcher delegation, KB tool declaration, OpenSpec
  proposal route.
- `roles/researcher/role.yaml:5-9` — existing `preferred_tools`
  pattern for `content_analyzer:*`.
- `src/assistant/harnesses/deep_agents.py:29-38` — `skills_dirs` flow.
- `src/assistant/cli.py:146-159` — `/role` rebuild (why `/method`
  needs to be separate).
- `src/assistant/core/composition.py:49-52` — `preferred_tools`
  rendering today (advisory only).
- `openspec/roadmap.md` P3 `http-tools-layer` — when real tool
  wiring lands.
