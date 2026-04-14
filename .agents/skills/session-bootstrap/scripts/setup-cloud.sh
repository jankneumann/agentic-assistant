#!/bin/bash
# setup-cloud.sh — One-time cloud environment setup.
#
# This is the Codex copy of the skill.  The Claude Code copy lives at
# .claude/skills/session-bootstrap/scripts/setup-cloud.sh — each harness
# invokes its own copy so the two can diverge later if needed.
#
# For the Codex cloud "Setup Script" field, paste:
#   script="$(find "$(pwd)" -maxdepth 7 -path '*/.agents/skills/session-bootstrap/scripts/setup-cloud.sh' -print -quit)"
#   bash "$script"
#
# (Claude Code users: see .claude/skills/session-bootstrap/scripts/setup-cloud.sh
# for the matching snippet that targets .claude/.)
#
# This works whether $(pwd) at Setup-Script time is the repo root (local dev)
# or the parent of the clone (Claude Code web, where $(pwd) is /home/user and
# the repo is at /home/user/<reponame>/).  Do NOT use a literal
# "$(pwd)/.agents/..." path — on cloud harnesses that resolves to
# /home/user/.agents/... which doesn't exist, yielding "file not found".
#
# Or paste the full script contents if the skill isn't installed yet.
# Runs as root on new sessions only (skipped on resume).
#
# Claude Code web pre-installs: Python 3.x, uv, pip, npm, pnpm, docker, git.
# Codex pre-installs similar tools via the "universal" image.
#
# This script installs project-specific deps that aren't pre-installed.
# On resume, the SessionStart hook (bootstrap-cloud.sh) verifies everything
# is still in place and repairs anything missing.

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

log "=== Cloud Setup — $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
log "Project: $PROJECT_DIR"
cd "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# Python venvs — auto-detect pyproject.toml locations
# ---------------------------------------------------------------------------
install_venvs() {
    local targets=()
    [[ -f "$PROJECT_DIR/pyproject.toml" ]] && targets+=("$PROJECT_DIR")
    [[ -f "$PROJECT_DIR/agent-coordinator/pyproject.toml" ]] && targets+=("$PROJECT_DIR/agent-coordinator")
    [[ -f "$PROJECT_DIR/skills/pyproject.toml" ]] && targets+=("$PROJECT_DIR/skills")

    for target in "${targets[@]}"; do
        local label="${target#"$PROJECT_DIR"/}"
        [[ "$label" == "$PROJECT_DIR" ]] && label="(root)"
        log "Installing $label venv..."
        (cd "$target" && uv sync --all-extras) || log "WARNING: $label uv sync failed"
    done
}

# ---------------------------------------------------------------------------
# OpenSpec CLI
# ---------------------------------------------------------------------------
install_openspec() {
    if ! command -v openspec >/dev/null 2>&1; then
        log "Installing OpenSpec CLI..."
        npm install -g @fission-ai/openspec || log "WARNING: openspec install failed"
    fi
}

# ---------------------------------------------------------------------------
# Skills (only in source repo)
# ---------------------------------------------------------------------------
install_skills() {
    if [[ -f "$PROJECT_DIR/skills/install.sh" ]]; then
        log "Installing skills..."
        bash "$PROJECT_DIR/skills/install.sh" --mode rsync --deps none --python-tools none --force
    fi
}

# ---------------------------------------------------------------------------
# Frontend (if web/ or frontend/ exists)
# ---------------------------------------------------------------------------
install_frontend() {
    local dir=""
    [[ -f "$PROJECT_DIR/web/package.json" ]] && dir="$PROJECT_DIR/web"
    [[ -f "$PROJECT_DIR/frontend/package.json" ]] && dir="$PROJECT_DIR/frontend"

    if [[ -n "$dir" ]]; then
        local label="${dir#"$PROJECT_DIR"/}"
        log "Installing $label dependencies..."
        if command -v pnpm >/dev/null 2>&1; then
            (cd "$dir" && pnpm install --frozen-lockfile) || log "WARNING: pnpm install failed"
        else
            (cd "$dir" && npm ci) || log "WARNING: npm ci failed"
        fi
    fi
}

# ---------------------------------------------------------------------------
# Git parallel config
# ---------------------------------------------------------------------------
setup_git() {
    if git rev-parse --git-dir >/dev/null 2>&1; then
        git config --local rerere.enabled true
        git config --local rerere.autoUpdate true
        git config --local merge.conflictStyle zdiff3
        git config --local diff.algorithm histogram
        git config --local rebase.updateRefs true
        log "Git parallel config applied"
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
install_venvs
install_openspec
install_skills
install_frontend
setup_git
log "=== Setup complete ==="
