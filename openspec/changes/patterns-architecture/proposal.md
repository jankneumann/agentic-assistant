# Proposal: patterns-architecture

Roadmap slot: **P1.6** (inserted between P1.5 and P1.7 per `openspec/roadmap.md`).
Status: planning-only. **No production code changes.**

## Why

The `HarnessAdapter` abstraction introduced in P1 is a fat interface
(`src/assistant/harnesses/base.py:12-36`) with four abstract methods. That
shape served the single-harness vertical slice well, but five upcoming phases
each assume — implicitly and independently — a different extension model:

- **P1.7 `harness-advisor-extension`** wants to add an `advise()` method.
- **P12 `delegation-context`** wants to enrich `spawn_sub_agent()` context.
- **P11 `harness-routing`** wants to select harnesses by task shape.
- **P6 `a2a-server`** and **P17 `mcp-server-exposure`** want cross-process
  agent communication without saying how that intersects the harness layer.
- **P16 `cli-harness-integrations`** anticipates Claude Code / Codex / ADK /
  MS AF as peers — but each has wildly different native idioms.

Without a shared framing, each phase invents conventions that the others
must later retrofit. The P1.7 Gate 1 review surfaced this concretely:
adding `advise()` as a fifth abstract method would work for P1.7, but
scales poorly (every new pattern × every new harness = a new `raise
NotImplementedError`).

**Why now**: P1.7 is blocked on this framing (per Gate 1 revision). P2
memory-architecture is downstream. Landing a small framing document before
either unblocks both on the same architectural terms.

## What Changes

- **New document**: `design.md` articulating a four-layer model —
  (L1) assistant framework, (L2) harness runtime, (L3) patterns,
  (L4) transport — and how patterns are defined once but implemented
  per-harness.
- **New concept**: Capability — a conceptual identifier for a pattern a
  harness may support. No Python types prescribed; downstream proposals
  choose their own representation. ADVISE is the single worked example.
- **New concept**: CapabilityInfo — the declaration a harness makes about
  a capability: mode (native / emulated / transport-mediated /
  not_supported), cost_characteristic (qualitative), optional notes.
- **New concept**: required_capabilities — a role-level declaration of
  which capabilities a role needs.
- **New concept**: factory contract (not algorithm) — the factory SHALL
  bind a role to a harness whose declared capabilities satisfy the role's
  required_capabilities. How it resolves ties or errors is deferred to
  P11.
- **New concept**: three implementation modes — native, emulated,
  transport-mediated. Transport enumeration only (A2A, MCP, HTTP);
  protocol mechanics deferred to P6 and P17.
- **No code**, **no implementation tasks**, **no contracts**.

**BREAKING**: None. P1.6 defines concepts that downstream proposals adopt.

## Capabilities

### New Capabilities

- `patterns-architecture`: Architectural requirements for the pattern
  system. Every requirement is conceptual — none prescribes a Python
  type, file location, or concrete algorithm.

### Modified Capabilities

*None.* Deltas to `harness-adapter`, `role-registry`, and
`delegation-spawner` are written by downstream proposals that reference
the concepts P1.6 establishes.

## Impact

- **New documents**: `design.md` (~200 lines), `specs/patterns-architecture/spec.md` (~6 ADDED requirements).
- **No source code changed. No new dependencies. No tests.**
- **Downstream adopters**: P1.7 (ADVISE), P12 (DELEGATE retrofit), P11
  (factory algorithm), P6/P17 (transport-mediated mode), P16 (new harness
  adapters).
- **Risk — narrow stress test**: Only ADVISE formalized. Mitigation:
  downstream proposals may propose delta specs to this capability.

## Approaches Considered

### Approach A — Single-document framing

One `design.md` covering all four layers + concepts + factory contract.
ADVISE discussed inline. **Effort**: S. *Smallest scope; P1.7 must infer
application from abstract language.*

### Approach B — Framing + ADVISE worked example appendix *(Selected)*

Approach A, plus **Appendix A** inside `design.md` walking through ADVISE
as a Capability: role declaration, harness declaration (native + emulated),
transport-mediated plug-in when P6 lands. Still conceptual — no types or
code. **Effort**: S. *Makes framing tangible for P1.7 implementers.*

### Approach C — Framing + separate ADRs per decision

Approach A, plus individual ADR files per decision. Maximum traceability.
**Effort**: M. *Introduces ADR convention as side-effect; better done
separately.*

### Selected Approach

**Approach B.** Confirmed at Gate 1. Adds the worked ADVISE example that
makes the framing concrete for P1.7 without introducing types or a new
document convention.
