# Prompt: improve `/cleanup-feature` skill — submodule handling

Hand this prompt to the **agentic-coding-tool** agent.

---

## Context

The `agentic-assistant` repo uses git submodules for private persona
configs (`personas/<name>/` mount points). The OpenSpec autopilot flow
(`/plan-feature` → `/implement-feature` → `/validate-feature` →
`/cleanup-feature`) handles feature lifecycle through merge + archive.
The `cleanup-feature` skill does the final step: pre-merge gates,
`gh pr merge`, `openspec archive`, worktree teardown, branch cleanup.

Two submodule-related issues surfaced in a real cleanup run
(`test-privacy-boundary`, merged as commit `2069784` on
`jankneumann/agentic-assistant`) that the skill currently does not
handle. Both are mechanical, reproducible, and fixable in the skill's
scripts + SKILL.md.

## Scope of your task

Improve the cleanup-feature skill to address both issues. Expected
deliverables:

1. Code/script changes under `.claude/skills/cleanup-feature/` and/or
   `.claude/skills/worktree/scripts/worktree.py`.
2. SKILL.md updates documenting the new behavior.
3. One or more tests under `.claude/skills/cleanup-feature/tests/` (or
   wherever tests live in that skill — check existing conventions) that
   reproduce both failure modes and prove the fixes.
4. A PR against `main` with the fix.

**Do not invoke the full autopilot** for this work — it's a skill
improvement, not an OpenSpec feature. Branch + commit + PR directly.

## Issue 1: worktree teardown fails on worktrees with initialized submodules

**Reproducer** (observed live):

```bash
# Cleanup phase tries to remove the feature worktree:
python3 .claude/skills/worktree/scripts/worktree.py teardown <change-id>

# Fails with:
#   Error: git worktree remove /Users/.../test-privacy-boundary failed (exit 128)
#     fatal: working trees containing submodules cannot be moved or removed
```

Git refuses to remove a worktree that has an initialized submodule
checkout. Running `git submodule deinit -f <submodule>` inside the
worktree first is **supposed** to fix this, but in practice git still
blocks the removal because some submodule metadata persists in the
worktree's `.git/modules/` linkage. The working fix for this run was:

```bash
git worktree remove --force .git-worktrees/<change-id>
```

The `--force` is safe here because: (a) the worktree's branch state is
already pushed to origin (merge happened before teardown), (b) the
submodule content is already committed + pushed to the submodule's
private remote, (c) any local changes inside the worktree are either
committed or explicitly unwanted (teardown implies the worktree is
done).

**What the skill should do:**

- Before calling `git worktree remove`, attempt `git submodule deinit -f`
  inside the worktree for any initialized submodules. This is the
  clean path when it works.
- If plain `git worktree remove` still fails with *"working trees
  containing submodules cannot be moved or removed"*, fall back to
  `git worktree remove --force` automatically — with a log line
  explaining the fallback. Don't make the operator figure it out.
- Document the fallback in `SKILL.md` under the teardown step so
  reviewers understand the `--force` is intentional.

**Edge case to handle correctly:** The fallback to `--force` should
only fire for the specific *"working trees containing submodules"*
error. Do not blanket-`--force` on any `git worktree remove` failure —
other errors (dirty working tree, conflicting file edits) deserve
operator attention, not automated suppression.

## Issue 2: submodule main branch not fast-forwarded after parent merge

**Reproducer** (observed live):

After `test-privacy-boundary` was merged to parent's main, the parent's
`main` branch recorded the submodule at SHA `a82d7f8` (via the gitlink
bump). But the submodule's own `main` branch on the submodule remote
stayed at the pre-change SHA `844efa0`. The submodule's feature branch
`openspec/test-privacy-boundary` contained the new commits, but nothing
merged them into submodule-main.

This is a real footgun: a fresh clone of the parent repo + `git
submodule update --init` works fine (the parent SHA-record is all that
matters for the parent's test suite). But anyone cloning *just* the
submodule, or anyone running `git submodule update --remote` to follow
the submodule's main branch, gets the *old* state. The submodule's
`main` silently lags behind what's actually in production.

**What the skill should do:**

After a successful parent merge, and after verifying the submodule
feature branch is merged-equivalent to the gitlink SHA:

1. Inside each changed submodule (detect via `git diff main@{1} main
   -- <submodule-mount>`), fetch + fast-forward the submodule's local
   main to the SHA the parent records.

   ```bash
   SUB_SHA=$(git ls-tree main <submodule-mount> | awk '{print $3}')
   git -C <submodule-mount> fetch origin main
   git -C <submodule-mount> switch main
   # Fast-forward only — never force-merge
   git -C <submodule-mount> merge --ff-only "$SUB_SHA"
   # If FF is impossible, log a warning and STOP (don't guess)
   ```

2. Push the submodule's main to its private remote:

   ```bash
   git -C <submodule-mount> push origin main
   ```

3. Delete the submodule's feature branch (local + remote), same way
   the parent branch is cleaned up.

**Credentials / access**: The same credentials that let the
cleanup-feature skill merge the parent PR are NOT necessarily
sufficient for the submodule's private remote. If the submodule push
fails with an auth error, the skill should:

- Log a clear diagnostic naming the submodule + its remote URL
- Write an operator-handoff message (the manual command to run)
- Proceed with the rest of cleanup rather than aborting

**Where to thread this in:** The existing cleanup-feature flow does the
parent merge, then fetches main, then runs `make architecture`, then
migrates tasks, then archives OpenSpec. The submodule fast-forward
belongs **after the parent fetch** (so the SHA we read is the
post-merge one) and **before the worktree teardown** (so if the
teardown includes `submodule deinit`, the submodule's main is already
up-to-date and the deinit is pure cleanup, not cleanup + lost work).

## Non-goals

- Do NOT implement cross-repo push wrapper logic that parallels
  `scripts/push-with-submodule.sh`. That script is for the
  implementation side (bumping submodule + parent in a single operator
  action). The cleanup-feature flow happens AFTER that bumping has
  already landed on parent's main — the cleanup's job is to make the
  submodule's *own* main catch up. Different concern, simpler code.
- Do NOT try to detect stale submodule state across the whole repo.
  Scope to submodules that actually changed in the merged commit
  range (`git diff main@{1}..main -- personas/`).
- Do NOT auto-open a PR in the submodule repo to merge the feature
  branch. Direct `git push origin main` after a verified fast-forward
  is correct for submodule repos that don't require review (which is
  the current `agentic-assistant-config-personal` setup). If the
  fast-forward fails because non-FF changes exist on submodule-main,
  bail out with a clear message rather than guessing.

## Acceptance criteria

1. Running `/cleanup-feature <change-id>` on a feature that bumped a
   submodule SHA produces, on success, a repo state where:
   - Parent `main` records the new submodule SHA ✓ (existing behavior)
   - Submodule's `main` branch is fast-forwarded to that SHA ✓ (new)
   - Submodule's feature branch is deleted locally + on the submodule
     remote ✓ (new)
   - Parent worktree is removed cleanly without the operator needing
     to run `--force` manually ✓ (new)

2. Running `/cleanup-feature <change-id>` on a feature that did NOT
   change any submodule SHA behaves identically to today (no
   regressions on non-submodule changes).

3. Running `/cleanup-feature <change-id>` when the submodule push
   fails for credential reasons logs a clear operator handoff and
   completes the rest of the cleanup (does not block on push failure).

4. Tests cover both issues with a reproducer that would have caught
   the original failures.

## Reference commits / artifacts

- Parent merge that exhibited both issues:
  `jankneumann/agentic-assistant@2069784` ("chore(openspec): archive
  test-privacy-boundary, sync spec delta into specs/")
- Submodule SHA that needed fast-forwarding:
  `jankneumann/agentic-assistant-config-personal@a82d7f8`
- The original cleanup-feature run that surfaced both issues is in
  `openspec/changes/archive/2026-04-13-test-privacy-boundary/session-log.md`
  under "Phase: Cleanup" (if written — it may have been skipped per
  the non-blocking clause)
- Relevant existing scripts:
  - `.claude/skills/cleanup-feature/SKILL.md` (step 8.5 "Remove
    Worktrees")
  - `.claude/skills/worktree/scripts/worktree.py` (`teardown`
    subcommand)

## Suggested commit shape

```
feat(cleanup-feature): handle submodules during worktree teardown + fast-forward submodule main

- worktree.py teardown: auto-deinit submodules, fall back to --force
  only for the "working trees containing submodules" error class
- cleanup-feature SKILL.md: new "Submodule main fast-forward" step
  after step 4 (update local repository), before step 5 (migrate
  open tasks). Detects submodules whose SHA changed in the merge
  range, fast-forwards their main, pushes to submodule remote,
  deletes feature branches.
- tests: reproducer harness for both failure modes using a throwaway
  submodule structure in tmp_path.
```

Thanks.
