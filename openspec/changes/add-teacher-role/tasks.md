# Tasks: add-teacher-role

Task ordering follows TDD: spec scenarios precede the implementation that
satisfies them. Each implementation task declares its spec-scenario and
dependency task(s).

## Phase 1 — Role scaffold

- [ ] 1.1 Create `roles/teacher/role.yaml` with:
  - `name: teacher`, `display_name: "Teacher"`, `description:
    "Structured teaching loop toward transferable understanding"`
  - `preferred_tools: [content_analyzer:search,
    content_analyzer:knowledge_graph]`
  - `delegation: { can_spawn_sub_agents: true, max_concurrent: 1,
    allowed_sub_roles: [researcher] }`
  - `planning: { always_plan: false, decomposition_style: task_oriented,
    max_depth: 1 }`
  - `context: { prioritize_sources: true, save_findings: false,
    output_format: conversational }`
  - `skills_dir: "./roles/teacher/skills"`
  - `prompt_position: after_persona`

  **Spec scenarios**: teacher-role/teacher-role-is-discoverable,
  teacher-role/teacher-declares-researcher-delegation,
  teacher-role/teacher-declares-kb-tool-preferences
  **Design decisions**: D5, D6, D9
  **Dependencies**: none

- [ ] 1.2 Create `roles/teacher/prompt.md` with:
  - Role header + purpose (one paragraph: "You drive a structured
    teaching loop with the user toward transferable mastery of a
    topic they name").
  - Meta-behavior section covering: offer-method-on-first-turn (D2),
    honor-CLI-or-REPL-method-directive (D4), skill-switch transition
    protocol (D7), completion-signal awareness (D8).
  - Rules section covering: teach one concept layer at a time; never
    re-teach what the user has demonstrated; flag analogies as
    analogies; don't proceed without user response; never drift into
    `researcher` or `writer` output shapes.
  - Delegation guidance: when the user asks to verify a concept OR
    the teacher flags its own uncertainty, spawn a `researcher`
    sub-agent with a scoped verification task; wait for its return
    before Step 1.
  - Tool-reaching guidance: follow the active skill's instructions for
    *when* to consult `content_analyzer:*` tools; do NOT reach for
    them outside the skill's stated allowance.

  **Spec scenarios**: teacher-role/teacher-offers-method-choice-on-first-turn,
  teacher-role/teacher-honors-explicit-method-directive,
  teacher-role/skill-switch-transition-preserves-state
  **Design decisions**: D1, D2, D4, D5, D6, D7, D8
  **Dependencies**: 1.1

## Phase 2 — Skills

- [ ] 2.1 Create `roles/teacher/skills/feynman.md`. Contains the full
  Feynman loop adapted from the user's provided prompt: Step 1
  (≤150-word plain-language explanation + one flagged analogy + "explain
  it back to me" prompt), Step 2 (wait), Step 3 (1-10 score, bulleted
  gap list, ≤100-word re-teach of gaps only), Step 4 (repeat 2-3 until
  user scores 9+), completion signal ("You've got it. Here's the
  one-sentence definition..."). Also includes the tool-timing guidance
  per D6: *knowledge_graph consultation permitted before Step 1 only;
  cite the canonical definition as the anchor; do NOT consult between
  steps*.

  **Spec scenarios**: teacher-role/feynman-skill-defines-explain-check-reteach-loop
  **Design decisions**: D6, D8
  **Dependencies**: 1.1

- [ ] 2.2 Create `roles/teacher/skills/socratic.md`. Contains the
  question-only loop: Step 1 (one open question that probes the user's
  existing model of the topic, no explanation), Step 2 (wait), Step 3
  (follow-up question that targets the assumption or gap surfaced by
  the user's answer; the assistant never states facts, only asks),
  loop repeats, completion signal ("You're teaching yourself now.
  Here's the frame you'd use to open this for someone else..."). Tool
  guidance: `knowledge_graph` may be consulted silently (not cited to
  user) to ensure the next question lands on a real gap; `search` for
  examples only if the user asks.

  **Spec scenarios**: teacher-role/socratic-skill-defines-question-only-loop
  **Design decisions**: D6, D8
  **Dependencies**: 1.1

## Phase 3 — CLI and REPL

- [ ] 3.1 Write tests in `tests/test_cli.py`:
  - `test_method_flag_with_teacher_role_accepted` — invoke CLI with
    `-p personal -r teacher --method feynman`, assert no UsageError,
    first-turn directive to the agent contains `feynman`.
  - `test_method_flag_without_teacher_role_rejected` — invoke with
    `-r coder --method feynman`, assert `click.UsageError` with
    message containing `--method requires --role teacher`.
  - `test_method_flag_with_unknown_method_rejected` — invoke with
    `-r teacher --method made_up`, assert `UsageError` listing the
    available method names (derived from
    `roles/teacher/skills/*.md`).
  - `test_methods_repl_command` — assert `/methods` prints the
    discoverable skill files with active marker on the current one.
  - `test_method_repl_command_switches` — assert `/method socratic`
    after `/method feynman` records the new active method in the REPL
    state (without rebuilding the harness; assert
    `_create_harness` call count is unchanged).
  - `test_method_repl_command_rejects_invalid` — assert `/method
    bogus` prints an error listing valid methods and does not change
    the active method.

  **Spec scenarios**: cli-interface/teacher-method-flag,
  cli-interface/teacher-methods-repl-command,
  cli-interface/teacher-method-repl-switch
  **Design decisions**: D3, D4
  **Dependencies**: 1.1, 2.1, 2.2

- [ ] 3.2 Implement `--method` / `-m` option on `main()` in
  `src/assistant/cli.py`. Validation logic:
  - `method` is None → no-op.
  - `method` is not None AND `role_name != "teacher"` → raise
    `click.UsageError("--method/-m requires --role teacher.")`.
  - `method` is not None AND role IS `teacher` → list the skill files
    under `roles/teacher/skills/`; if `method` is not among them,
    raise `click.UsageError("Unknown method '<m>'. Available: <list>.")`.
  - Valid method → store in REPL state, include in the first
    user-turn prefix as a system directive: *"Use the `<method>`
    method. Begin Step 1 now for the topic the user provides in their
    next message."*

  **Spec scenarios**: cli-interface/teacher-method-flag
  **Design decisions**: D3, D4
  **Dependencies**: 3.1

- [ ] 3.3 Implement `/methods` REPL command. Lists skill files from
  `roles/teacher/skills/*.md` (strip extension for display), marks the
  active method with `←`. If the current role is not `teacher`, print
  "`/methods` is only available when role is `teacher`." and continue.

  **Spec scenarios**: cli-interface/teacher-methods-repl-command
  **Design decisions**: D3
  **Dependencies**: 3.1

- [ ] 3.4 Implement `/method <name>` REPL command. Behavior:
  - Current role is not `teacher` → print same guard message as in
    3.3; continue.
  - Method name not found among skill files → print
    `"Unknown method '<name>'. Available: <list>."` and continue.
  - Valid → update REPL state's active method; inject a directive
    into the *next* agent invocation: *"From this turn forward use
    the `<name>` method. Summarize where we are in the current
    method's loop in ≤3 sentences, announce the switch, then enter
    Step 1 of the new method."* Do NOT rebuild the harness/agent
    (contrast with `/role <name>` at `cli.py:146-159` which does).

  **Spec scenarios**: cli-interface/teacher-method-repl-switch
  **Design decisions**: D3, D4, D7
  **Dependencies**: 3.1

- [ ] 3.5 Update the REPL prompt prefix. When the active role is
  `teacher` AND an active method is set, display
  `[Teacher:<method>]>` instead of the generic `[Teacher]>`. No
  change when role is not `teacher`.

  **Spec scenarios**: cli-interface/teacher-method-repl-switch
  **Design decisions**: D4
  **Dependencies**: 3.4

- [ ] 3.6 Update the initial REPL Commands help line (currently
  `cli.py:128-130`) to include `/method <name>` and `/methods` when
  the starting role is `teacher`. Other roles see the existing help
  line unchanged.

  **Spec scenarios**: cli-interface/teacher-method-repl-switch
  **Design decisions**: D3
  **Dependencies**: 3.3, 3.4

## Phase 4 — Role-registry tests

- [ ] 4.1 Write in `tests/test_role_registry.py`:
  - `test_teacher_role_is_discoverable` — assert `"teacher" in
    RoleRegistry(roles_dir).discover()`.
  - `test_teacher_preferred_tools` — load teacher, assert
    `preferred_tools == ["content_analyzer:search",
    "content_analyzer:knowledge_graph"]`.
  - `test_teacher_delegates_only_to_researcher` — load teacher,
    assert `delegation["allowed_sub_roles"] == ["researcher"]` and
    `delegation["max_concurrent"] == 1`.
  - `test_teacher_skills_dir_resolves` — load teacher, assert
    `skills_dir == "./roles/teacher/skills"` AND `Path(skills_dir)`
    exists AND contains `feynman.md` and `socratic.md`.

  **Spec scenarios**: teacher-role/teacher-role-is-discoverable,
  teacher-role/teacher-declares-researcher-delegation,
  teacher-role/teacher-declares-kb-tool-preferences,
  teacher-role/teacher-skills-directory-populated
  **Design decisions**: D5, D6
  **Dependencies**: 1.1, 2.1, 2.2

## Phase 5 — Roadmap and docs

- [ ] 5.1 Add a row to `openspec/roadmap.md`'s "Proposal sequence"
  table for `add-teacher-role`, kind `non-phase`, status `pending`
  (flips to `in-progress` when this proposal is implemented and
  `archived` on final archive). Description: "Add `teacher` role
  with Feynman + Socratic skill files; add `--method` CLI flag and
  `/method` / `/methods` REPL commands; forward-declare
  `content_analyzer:*` preferred tools for post-P3 wiring."

  **Spec scenarios**: n/a (roadmap bookkeeping)
  **Design decisions**: none
  **Dependencies**: none

- [ ] 5.2 Add a corresponding item to `openspec/roadmap.yaml` with
  `item_id: add-teacher-role`, `status: pending`, `depends_on: []`
  (no functional dependency on any P-phase), `effort: S`,
  `acceptance_outcomes` naming the spec capabilities populated
  (`teacher-role`) and the CLI additions verified.

  **Spec scenarios**: n/a
  **Design decisions**: none
  **Dependencies**: 5.1

- [ ] 5.3 Append a note to `roles/teacher/role.yaml`'s header comment
  (if feasible; YAML comments) pointing at this proposal:
  `# See openspec/changes/add-teacher-role/ for the design`. Low
  value but cheap signal for future readers browsing the role.

  **Spec scenarios**: n/a
  **Design decisions**: none
  **Dependencies**: 1.1

## Phase 6 — Validation

- [ ] 6.1 Run `openspec validate add-teacher-role --strict`. Fix any
  reported validation errors before proceeding.
  **Spec scenarios**: n/a
  **Dependencies**: all prior tasks.

- [ ] 6.2 Run `uv run pytest tests/` from repo root. Must exit 0.
  Covers Phase 3 CLI tests and Phase 4 role-registry tests.
  **Spec scenarios**: all populated in specs/
  **Dependencies**: 3.6, 4.1

- [ ] 6.3 Manual smoke test: `uv run assistant -p personal -r teacher`
  — verify the REPL launches, the first-turn message offers Feynman
  and Socratic, `/methods` lists both, `/method feynman` then
  `/method socratic` switches without losing prior context (inspect
  the prompt prefix to confirm `[Teacher:feynman]>` →
  `[Teacher:socratic]>`).
  **Spec scenarios**: n/a (exploratory)
  **Dependencies**: 6.2
