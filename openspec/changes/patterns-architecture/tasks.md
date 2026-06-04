# Tasks: patterns-architecture

> Planning-only proposal. No implementation code. Tasks are review and
> documentation activities.

## Phase 1 — Write and validate artifacts

- [ ] 1.1 Write `design.md` — four-layer model, Capability, CapabilityInfo,
  required_capabilities, factory contract, implementation modes, anti-patterns,
  Appendix A (ADVISE worked example)
  **Spec scenarios**: patterns-architecture.1 (four-layer model),
  patterns-architecture.2 (capability identifier),
  patterns-architecture.3 (capability declaration),
  patterns-architecture.6 (implementation mode enumeration)
  **Dependencies**: None

- [ ] 1.2 Write `specs/patterns-architecture/spec.md` — ADDED requirements
  with SHALL-first language, WHEN/THEN scenarios per requirement
  **Spec scenarios**: all patterns-architecture scenarios
  **Dependencies**: 1.1

- [ ] 1.3 Run `openspec validate patterns-architecture --strict`
  **Dependencies**: 1.1, 1.2

## Phase 2 — Cross-reference and downstream readiness

- [ ] 2.1 Verify that `openspec/roadmap.md` P1.6 entry matches the
  delivered artifacts; update if the scope shifted during authoring
  **Dependencies**: 1.3

- [ ] 2.2 Verify that `openspec/changes/harness-advisor-extension/proposal.md`
  status header references P1.6 correctly and that the Tier 1 draft is
  consistent with Appendix A's ADVISE framing
  **Dependencies**: 1.3

- [ ] 2.3 Add `docs/gotchas.md` entry for AP1 (transcript summarization
  anti-pattern) and AP2 (advisor ≠ delegation), referencing
  `design.md#d6--anti-patterns`
  **Dependencies**: 1.1
