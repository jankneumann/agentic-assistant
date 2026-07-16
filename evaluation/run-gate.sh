#!/usr/bin/env bash
# Eval gate (P27 eval-simulation-loop).
#
# Runs the gen-eval simulation scenario suites against the simulation
# persona and exits nonzero on any scenario failure. Consumed by:
#   - CI / scheduled runs (machines with the tools repo checked out)
#   - P28 continual-learning (learned changes must pass the gate)
#   - prompt/routing config changes (run before merging)
#
# Reuse policy (ADR 0006, evaluation/README.md): gen-eval is a CONSUMER
# of this repo, never a dependency. This script shells out to the
# gen-eval project owned by the agentic-coding-tools repo. Machines
# without that checkout SKIP with a clear message and exit 0 — unless
# EVAL_GATE_REQUIRE=1, which turns a missing gen-eval into a hard
# failure (G7-style strictness opt-in, inverted: the gate is advisory
# by default because fresh clones/CI must stay green without siblings).
#
# Environment:
#   GEN_EVAL_PROJECT   path to the gen-eval project
#                      (default: ../agentic-coding-tools/packages/gen-eval)
#   EVAL_GATE_REQUIRE  1 = fail (exit 3) when gen-eval is unavailable
#   SIM_PORT           simulator port (default 8901; must match the
#                      descriptor's startup block if overridden)
#
# The simulator lifecycle (startup/health/teardown) is owned by the
# descriptor's startup block (evaluation/descriptors/
# agentic-assistant-simulation.yaml), mirroring the serve descriptor.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

GEN_EVAL_PROJECT="${GEN_EVAL_PROJECT:-$REPO_ROOT/../agentic-coding-tools/packages/gen-eval}"
SIM_PORT="${SIM_PORT:-8901}"

gen_eval_unavailable() {
  # $1: reason
  if [ "${EVAL_GATE_REQUIRE:-0}" = "1" ]; then
    echo "eval-gate: FAIL — $1 and EVAL_GATE_REQUIRE=1 (set" \
         "GEN_EVAL_PROJECT to the agentic-coding-tools gen-eval package)." >&2
    exit 3
  fi
  echo "eval-gate: SKIP — $1." \
       "The gate is advisory on machines without a working" \
       "agentic-coding-tools checkout (ADR 0006); set EVAL_GATE_REQUIRE=1" \
       "to make this fatal."
  exit 0
}

if [ ! -d "$GEN_EVAL_PROJECT" ]; then
  gen_eval_unavailable "gen-eval project not found at $GEN_EVAL_PROJECT"
fi

# Availability probe: the directory existing is not enough — offline
# environments carry a lock-resolution stub of the package with no
# console script. A probe failure is an availability condition (SKIP /
# REQUIRE-fail), never a scenario failure.
if ! uv run --project "$GEN_EVAL_PROJECT" gen-eval --help >/dev/null 2>&1; then
  gen_eval_unavailable \
    "gen-eval at $GEN_EVAL_PROJECT is not runnable (stub checkout?)"
fi

if [ ! -x "$REPO_ROOT/.venv/bin/assistant" ]; then
  echo "eval-gate: FAIL — $REPO_ROOT/.venv/bin/assistant missing." \
       "Run 'uv sync' in $REPO_ROOT first (the CLI descriptor launches" \
       "evaluation/bin/assistant-quiet, which needs the venv)." >&2
  exit 2
fi

# Simulation persona environment: personas root + one SIM_<SOURCE>_URL
# per simulated source directory (convention shared with
# `assistant simulate`, which prints the same export lines).
export ASSISTANT_PERSONAS_DIR="$REPO_ROOT/evaluation/simulation/personas"
for source_dir in "$REPO_ROOT"/evaluation/simulation/sources/*/; do
  name="$(basename "$source_dir")"
  var="SIM_$(echo "$name" | tr '[:lower:]' '[:upper:]')_URL"
  export "$var=http://127.0.0.1:$SIM_PORT/$name"
  echo "eval-gate: $var=http://127.0.0.1:$SIM_PORT/$name"
done

cd "$REPO_ROOT"  # descriptor startup uses repo-relative paths

DESCRIPTOR="$REPO_ROOT/evaluation/descriptors/agentic-assistant-simulation.yaml"
failures=0
for scenario in "$REPO_ROOT"/evaluation/simulation/scenarios/*.yaml; do
  echo "eval-gate: running $(basename "$scenario")"
  if ! uv run --project "$GEN_EVAL_PROJECT" gen-eval run \
      --descriptor "$DESCRIPTOR" \
      --scenario "$scenario"; then
    echo "eval-gate: FAIL — $(basename "$scenario")" >&2
    failures=$((failures + 1))
  fi
done

if [ "$failures" -gt 0 ]; then
  echo "eval-gate: FAIL — $failures scenario file(s) failed." >&2
  exit 1
fi
echo "eval-gate: PASS — all simulation scenarios green."
