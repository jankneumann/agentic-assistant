# Session Log: durable-sessions

---

## Phase: Cleanup (2026-07-22)

**Agent**: claude_code | **Session**: N/A

### Decisions

1. **Merged via merge commit rather than the OpenSpec default rebase** — the
   operator selected rebase to preserve granular commit history, but GitHub
   refused with `This branch can't be rebased`. The branch carries 11 internal
   merge commits, and a rebase must replay every commit as a linear sequence,
   which is impossible for commits with two parents. A merge commit was chosen
   as the fallback because it preserves all 100 commits AND the 11 internal
   merges, serving the original blame/bisect intent better than a rebase would
   have.
2. **Skipped the `make decisions` regeneration step** — the skill treats this as
   required, but this repository has no `Makefile`, so neither `make decisions`
   nor `make architecture` exists. There is also no `validate-decision-index` CI
   job, so the failure mode the skill warns about is absent here. Inspection of
   `docs/decisions/` showed hand-authored retroactive ADRs seeded by the X3
   repo-hygiene task, using prose Status/Context/Decision/Consequences sections,
   not a derived index. Running the generator over them would risk destroying
   authored content, so the step was skipped deliberately rather than forced.
3. **Ran cleanup on main directly instead of in a cleanup worktree** — matches
   the 2026-05-21 precedent for `--post-merge` mode, which has no
   parallel-implementation collision risk. The active-agent guard reported
   `clear: no active agents` at session start.
4. **No task migration required** — `tasks.md` showed 29 of 29 tasks complete,
   so Step 5 migration to coordinator issues or a follow-up proposal was skipped.

### Alternatives Considered

- Squash merge: rejected because collapsing 57041 added lines into a single
  commit would make future `git bisect` and `git blame` on this work useless.
- Manually flattening the 11 internal merge commits to enable a true rebase:
  rejected as high risk and high effort for a branch of this size, with no
  benefit over a merge commit.
- Running `archive_index.py --emit-decisions` directly in place of the missing
  `make decisions` target: rejected because the ADRs are hand-authored, not
  derived, and the generator could overwrite them.

### Trade-offs

- Accepted a merge commit plus 100 commits on main over a single squashed
  commit, because history granularity matters more than a linear main for a
  change spanning 18 executed phases.
- Accepted skipping the decision-index regeneration over forcing a generator
  this repo does not wire up, because the enforcing CI job does not exist and
  the overwrite risk is real.

### Open Questions

- [ ] Whether `docs/decisions/` should become a derived artifact in this repo,
      or stay hand-authored. The cleanup-feature skill assumes derived; this
      repo treats it as authored. The mismatch will recur on every cleanup.
- [ ] Whether a `Makefile` with `architecture` and `decisions` targets should be
      added so the skill's Step 4 and Step 6 run as written.

### Context

PR #43 was merged to main on 2026-07-22 with a merge commit after a rebase was
refused, landing 114 commits and 402 files. Before merging, CI was failing with
10 test failures traced to a relative `ASSISTANT_PERSONAS_DIR` in `ci.yml`
interacting with `CliRunner.isolated_filesystem()`; a one line fix anchoring the
path to `github.workspace` cleared all 10 and was pushed to the PR branch. The
merge also removed the gen-eval local path dependency that had kept main CI red
since 2026-06-10, so main returned to green for the first time in six weeks.
Archiving moved the change to `openspec/changes/archive/2026-07-22-durable-sessions/`
and merged delta specs across seven spec files, 5 added and 9 modified.
`openspec validate --all --strict` passed 36 of 36 items after the archive.

Pre-launch checklist and staged rollout (Steps 5c and 5d) are not applicable:
this change ships library and CLI surfaces with no deployed production
environment and no traffic gate to promote through, matching the disposition
used for the 2026-05-21 cleanup.
