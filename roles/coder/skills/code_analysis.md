# Skill: Code Analysis

## When to use
Reading unfamiliar code, diagnosing a bug, or planning a non-trivial change.

## Workflow
1. Map the entry points (CLI, main, server)
2. Trace execution through the affected modules
3. Inventory side effects (DB, filesystem, network)
4. Identify tests that exercise the code path
5. Summarize with a focused call graph or sequence diagram (in prose)

## Output Shape
- Entry point(s) and high-level flow
- Key files with 1-2-line purpose statements
- Tests covering the path (file:line)
- Risks and unknowns surfaced during the read
