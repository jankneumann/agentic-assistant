# Fix prompt — `session-bootstrap` `setup-cloud.sh` resolves wrong PROJECT_DIR on Claude Code web

**Target repo:** `agent-coding-tools` (the canonical source of the `session-bootstrap`
skill that gets installed into consumer repos via `skills/install.sh`).

**Target paths inside that repo:**

- `skills/session-bootstrap/scripts/setup-cloud.sh`
- `skills/session-bootstrap/SKILL.md`

This fix was authored against an installed copy in a consumer repo
(`agentic-assistant`), then redirected upstream so the fix survives the next
`skills/install.sh --mode rsync`. The consumer repo was left untouched; only
the canonical source in `agent-coding-tools` should be edited.

---

## Context: what broke

A consumer of the skill configured the Claude Code web Environment "Setup
Script" field with the snippet recommended in `SKILL.md`:

```bash
bash "$(pwd)/.claude/skills/session-bootstrap/scripts/setup-cloud.sh"
```

The cloud environment crashed during setup with a **"file not found"** error.
Root cause: on Claude Code web, `$(pwd)` at Setup-Script time is the **parent**
of the cloned repo (e.g. `/home/user`), not the repo root. The clone itself
lives at `/home/user/<reponame>/`. So the path evaluates to
`/home/user/.claude/skills/session-bootstrap/scripts/setup-cloud.sh`, which
doesn't exist.

`SKILL.md` even documents this assumption and claims it's true:

> Note: `$(pwd)` not `$CLAUDE_PROJECT_DIR` — the Setup Script runs before
> Claude Code launches, so `CLAUDE_PROJECT_DIR` isn't set yet. **The repo is
> already cloned at `$(pwd)`.**

That last sentence is the propagating bug — every consumer that copy-pastes
the snippet inherits it.

## Second, latent bug

Even if the invocation is fixed (e.g. hand-edited to an absolute path), the
script itself still resolves `PROJECT_DIR` incorrectly. Line 19 of
`setup-cloud.sh`:

```bash
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
```

At Setup-Script time `CLAUDE_PROJECT_DIR` is unset (that var is only injected
by Claude Code *hooks*, not by the cloud Setup Script stage), so this falls
back to `$(pwd) = /home/user`. Every subsequent
`[[ -f "$PROJECT_DIR/pyproject.toml" ]]` check then silently misses and no
venv, no skills, and no frontend deps get installed. The script exits 0 with
a "Project: /home/user" log and the consumer's session starts broken.

## Why `bootstrap-cloud.sh` doesn't have this bug

Its sibling script `bootstrap-cloud.sh` (the SessionStart hook) already uses
the correct pattern at lines 22–35: it derives `PROJECT_DIR` from
`BASH_SOURCE[0]` by walking up to the git root, with `CLAUDE_PROJECT_DIR` as
an override and `$(pwd)` only as a last-resort fallback. The fix is to copy
that idiom into `setup-cloud.sh`.

---

## Fix — exact changes

### 1. `skills/session-bootstrap/scripts/setup-cloud.sh` — harden PROJECT_DIR

Replace the existing block:

```bash
set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

log() { echo "[setup] $*"; }
```

with:

```bash
set -euo pipefail

# Resolve project root — Setup Script can run with cwd = parent of clone on
# Claude Code web (e.g. cwd is /home/user while the repo is at
# /home/user/<reponame>/), so we can't trust $(pwd) alone.  Priority:
#   1. $CLAUDE_PROJECT_DIR (set when Claude Code invokes the script).
#   2. Walk up from the script's own location to the git root (works in both
#      canonical skills/... and installed .claude/skills/... layouts).
#   3. Fall back to $(pwd) if we can't find a git root (keeps old behavior).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]]; then
    PROJECT_DIR="$CLAUDE_PROJECT_DIR"
elif git -C "$SCRIPT_DIR/../../.." rev-parse --show-toplevel >/dev/null 2>&1; then
    PROJECT_DIR="$(git -C "$SCRIPT_DIR/../../.." rev-parse --show-toplevel)"
elif git -C "$SCRIPT_DIR/../../../.." rev-parse --show-toplevel >/dev/null 2>&1; then
    PROJECT_DIR="$(git -C "$SCRIPT_DIR/../../../.." rev-parse --show-toplevel)"
else
    PROJECT_DIR="$(pwd)"
fi

log() { echo "[setup] $*"; }
```

This matches the idiom already in `bootstrap-cloud.sh` lines 22–35. The 3-up
branch handles the installed `.claude/skills/...` or `.agents/skills/...`
layout; the 4-up branch handles the canonical `skills/...` source tree. The
`${BASH_SOURCE[0]:-$0}` fallback keeps the script usable when its contents
are pasted inline (e.g. into a Setup-Script UI field instead of invoked via
path) — in that case `BASH_SOURCE` may be empty and `$0` takes over.

### 2. `skills/session-bootstrap/scripts/setup-cloud.sh` — update header comment

The existing header recommends the broken invocation. Replace:

```bash
# For the cloud Environment Settings "Setup Script" field, paste:
#   bash "$(pwd)/.claude/skills/session-bootstrap/scripts/setup-cloud.sh"
#
# Or paste the full script contents if the skill isn't installed yet.
```

with harness-aware guidance that matches SKILL.md (below). `install.sh` should
continue to emit one copy into `.claude/skills/` and one into `.agents/skills/`
when both targets are configured — so make the header note which copy it is.
If the canonical source is a single file that gets rsync'd into both target
directories, the simplest approach is to keep a **harness-agnostic header** in
the canonical source and let SKILL.md carry the two-snippet guidance:

```bash
# For the cloud Environment Settings "Setup Script" field of each harness,
# see skills/session-bootstrap/SKILL.md §1.  The snippet differs per harness
# (Claude Code paste-snippet targets */.claude/skills/..., Codex targets
# */.agents/skills/...), because install.sh rsyncs this file into both
# .claude/skills/session-bootstrap/scripts/ and
# .agents/skills/session-bootstrap/scripts/ of the consumer repo.
#
# Do NOT recommend a literal "$(pwd)/.claude/..." path — on Claude Code web
# that resolves to /home/user/.claude/... which doesn't exist, yielding
# "file not found".
#
# Or paste the full script contents if the skill isn't installed yet.
```

(If `install.sh` post-processes the header per target — e.g. rewriting
`.claude` ↔ `.agents` — prefer the per-harness headers in the section below
under "Alternative: per-harness header rewrite at install time".)

### 3. `skills/session-bootstrap/SKILL.md` — replace §1 wiring block

Current block (around line 49–59):

```markdown
### 1. Cloud Setup Script (Environment Settings UI)

The Setup Script field is a text area in the cloud UI (not committed to git).
Paste this one-liner — it calls the versioned script from the cloned repo:

\`\`\`bash
bash "$(pwd)/.claude/skills/session-bootstrap/scripts/setup-cloud.sh"
\`\`\`

Note: `$(pwd)` not `$CLAUDE_PROJECT_DIR` — the Setup Script runs before Claude Code
launches, so `CLAUDE_PROJECT_DIR` isn't set yet. The repo is already cloned at `$(pwd)`.
```

Replace with:

```markdown
### 1. Cloud Setup Script (Environment Settings UI)

The Setup Script field is a text area in the cloud UI (not committed to git).
The skill is installed into two parallel directories — `.claude/skills/` is
the canonical home for Claude Code, and `.agents/skills/` is the canonical
home for Codex — so each harness should invoke its own copy.

**Claude Code web** — paste into Environment Settings > Setup Script:

\`\`\`bash
script="$(find "$(pwd)" -maxdepth 7 -path '*/.claude/skills/session-bootstrap/scripts/setup-cloud.sh' -print -quit)"
bash "$script"
\`\`\`

**Codex** — paste into the environment's Setup Script field:

\`\`\`bash
script="$(find "$(pwd)" -maxdepth 7 -path '*/.agents/skills/session-bootstrap/scripts/setup-cloud.sh' -print -quit)"
bash "$script"
\`\`\`

Note: `CLAUDE_PROJECT_DIR` isn't set yet at Setup-Script time (Claude Code
injects it later, for hooks). On Claude Code web, `$(pwd)` at Setup-Script
time is the **parent** of the clone — typically `/home/user`, while the repo
lives at `/home/user/<reponame>/`. The older recommendation
`bash "$(pwd)/.claude/skills/session-bootstrap/scripts/setup-cloud.sh"` therefore
resolves to `/home/user/.claude/...` and fails with "file not found". The
harness-specific `find` patterns above handle both the cloud layout (pwd is
the parent) and the local-dev case (pwd is the repo root), and — because the
`-path` pattern pins the harness directory — each harness always executes its
own copy rather than whichever one happens to sort first. The script then
derives its own `PROJECT_DIR` from `BASH_SOURCE[0]`, so subsequent
`uv sync`/`npm install` commands run in the right directory.
```

### 4. Rationale for `-maxdepth 7`

From `$(pwd) = /home/user` on Claude Code web, the path depth to the script
is:

| depth | component                                                    |
|-------|--------------------------------------------------------------|
| 0     | `/home/user`                                                 |
| 1     | `<reponame>/`                                                |
| 2     | `.claude/`                                                   |
| 3     | `skills/`                                                    |
| 4     | `session-bootstrap/`                                         |
| 5     | `scripts/`                                                   |
| 6     | `setup-cloud.sh`                                             |

`-maxdepth 6` is the minimum that works; `7` gives one level of slack for
unusual layouts (e.g. an extra wrapper directory). Smaller values (the
original draft used `5`) fail to find the file.

### 5. Alternative: per-harness header rewrite at install time

If `skills/install.sh` already distinguishes Claude Code vs. Codex install
targets, consider having it rewrite the header comment of `setup-cloud.sh`
per target so that the deployed `.claude/skills/.../setup-cloud.sh` contains
only the `*/.claude/...` snippet in its header, and the deployed
`.agents/skills/.../setup-cloud.sh` contains only the `*/.agents/...` snippet.
This is purely a documentation-locality improvement; the SKILL.md §1 block
already covers both cases so it is not required for correctness.

---

## Verification

After applying the changes in `agent-coding-tools`, run this in a consumer
repo (e.g. `agentic-assistant`) whose `.claude/skills/` and `.agents/skills/`
are installed copies. The tests simulate the two conditions: (a) the
harness-scoped `find` snippets each hit their own copy, and (b) the script's
own PROJECT_DIR discovery works when cwd is the parent of the clone.

```bash
# 1. Reinstall the skill from agent-coding-tools into the consumer repo
bash path/to/agent-coding-tools/skills/install.sh --mode rsync --force

# 2. Syntax check
bash -n .claude/skills/session-bootstrap/scripts/setup-cloud.sh
bash -n .agents/skills/session-bootstrap/scripts/setup-cloud.sh

# 3. Each harness's find snippet resolves to its own copy
cd /home/user  # simulate Claude Code web cwd
script_claude="$(find "$(pwd)" -maxdepth 7 -path '*/.claude/skills/session-bootstrap/scripts/setup-cloud.sh' -print -quit)"
script_agents="$(find "$(pwd)" -maxdepth 7 -path '*/.agents/skills/session-bootstrap/scripts/setup-cloud.sh' -print -quit)"
[[ -f "$script_claude" ]] && echo "OK Claude Code script: $script_claude"
[[ -f "$script_agents" ]] && echo "OK Codex script:       $script_agents"
[[ "$script_claude" != "$script_agents" ]] && echo "OK distinct copies"

# 4. PROJECT_DIR discovery inside the script works when cwd is parent of clone
cd /home/user
env -u CLAUDE_PROJECT_DIR bash -x "$script_claude" 2>&1 | head -5
# Expected: "[setup] Project: /home/user/<reponame>"
# NOT:      "[setup] Project: /home/user"
```

Success criteria:

- `[setup] Project:` log line shows the repo root, not `/home/user`.
- `uv sync --all-extras` inside `install_venvs()` finds the project's
  `pyproject.toml` and installs the venv.
- No "file not found" error from the Setup-Script invocation itself.

## Bonus — fix downstream documentation

Any consumer repo that documents the old paste-snippet in its README,
onboarding docs, or `docs/gotchas.md` should be updated to reference the new
harness-specific snippets. A grep for `$(pwd)/.claude/skills/session-bootstrap`
across consumer repos catches most stale copies.
