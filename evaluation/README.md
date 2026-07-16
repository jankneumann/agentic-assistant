# evaluation/

Gen-eval assets for behavioral verification of the assistant:

- `descriptors/` — `gen_eval.descriptor.InterfaceDescriptor` YAML files
  describing how to launch and probe this repo's surfaces (CLI, AG-UI
  SSE server).
- `scenarios/` — gen-eval scenario YAML suites run against those
  descriptors.
- `bin/assistant-quiet` — wrapper used by gen-eval's `CliClient` to
  launch the CLI with deprecation noise suppressed.

## Running evaluations

**gen-eval is not a dependency of this package.** It is a *consumer* of
this repo (X3 repo-hygiene, 2026-07-16): the framework lives in the
`agentic-coding-tools` repo and invokes the assistant from the outside.
The previous `[tool.uv.sources]` path dependency broke `uv lock`/`uv
sync` on any standalone clone and was removed — see ADR 0006
(cross-repo reuse policy).

On a machine with the tools repo checked out beside this one:

```bash
# from the agentic-coding-tools repo (which owns the gen-eval package)
uv run --project ../agentic-coding-tools/packages/gen-eval \
  gen-eval run --descriptor ../agentic-assistant/evaluation/descriptors/agentic-assistant.yaml \
               --scenario  ../agentic-assistant/evaluation/scenarios/cli-help-sweep.yaml
```

(Adjust to the gen-eval CLI's current invocation; the point is that the
eval environment is the *tools* repo's, not this package's.)

Machines without the tools repo (CI, fresh clones, the GX10 node) can
build, test, and run the assistant normally; they simply skip gen-eval
runs. The P27 `eval-simulation-loop` phase owns making scheduled eval
runs a first-class, persona-simulated workflow.
