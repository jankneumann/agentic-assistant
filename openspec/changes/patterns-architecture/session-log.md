---

## Phase: Plan (2026-06-04)

**Agent**: claude_code | **Session**: claude/executor-advisor-pattern-NChzx

### Decisions
1. **Four-layer model over fat interface** -- The P1.7 Gate 1 review revealed
   that adding `advise()` as a fifth abstract method on `HarnessAdapter` would
   scale poorly as patterns and harnesses multiply. Adopted a layered
   architecture (framework / harness / patterns / transport) with a capability
   declaration system instead.
2. **Conceptual-only prescription** -- No Python types, file locations, or
   concrete algorithms. Downstream proposals choose their own representations.
   Maximizes flexibility for P1.7, P11, P12.
3. **ADVISE as sole worked example** -- Only the ADVISE capability is fully
   walked through. DELEGATE, MEMORY_SEARCH, PLAN, REFLECT are listed but not
   formalized. Downstream proposals delta-spec as they introduce each.
4. **Transport enumeration without mechanics** -- A2A, MCP, HTTP listed as
   transport protocols. Protocol selection deferred to P6 and P17.
5. **Factory contract without algorithm** -- Spec defines what the factory must
   guarantee (capability matching) but defers how (selection, fallback, tie-
   breaking) to P11 harness-routing.

### Alternatives Considered
- Tier 1 (advisor-only, method-on-HarnessAdapter): rejected because it would
  need a full refactor when more patterns and harnesses arrive.
- Separate ADRs per decision (Approach C): rejected because the repo does not
  use ADR format, and introducing it as a side-effect of content work is scope
  creep.
- Stress-testing against 3+ patterns (ADVISE + DELEGATE + MEMORY_SEARCH):
  rejected to minimize speculative scope. If the framing breaks for delegation,
  P12 revises.

### Trade-offs
- Accepted narrow stress test (ADVISE only) over comprehensive pattern coverage
  because real validation comes from downstream implementation, not from
  enumeration in a design document.
- Accepted conceptual-only prescription over concrete types because locking in
  Python types now might not fit all harness runtimes (Claude Code is a CLI, ADK
  is a different SDK). Better to let P1.7 pioneer the type system.

### Open Questions
- [ ] Should CapabilityInfo be immutable per harness, or can it degrade at
  runtime (e.g., network loss causes transport-mediated to become not_supported)?
- [ ] Does the existing `spawn_sub_agent()` method survive as the native
  DELEGATE implementation, or is it replaced when P12 retrofits?
- [ ] Should the anti-pattern registry (D6) be a living document?

### Context
P1.7 harness-advisor-extension was blocked at Gate 1 by an architectural
concern: the current fat-interface HarnessAdapter does not scale to multiple
harnesses times multiple patterns. This proposal establishes the shared framing
(four layers, capability declarations, factory contract) that P1.7 and five
subsequent phases all reference. Approach B (framing + ADVISE worked example)
selected to keep P1.7 implementers grounded in a concrete narrative.
