# Architecture Decision Records

Retroactive ADRs seeded by the X3 `repo-hygiene` task (task 2.2;
architecture-review finding H2). Each record uses the classic template
(Status / Context / Decision / Consequences) and cites the OpenSpec
change or analysis document where the decision originated.

Lifecycle: `PROPOSED → ACCEPTED → (SUPERSEDED | DEPRECATED)`. Numbers
are sequential and never reused; superseded ADRs stay in place with a
link to their replacement.

## Index

| # | Title | Status | Date |
|---|-------|--------|------|
| [0001](0001-sdk-host-harness-split.md) | Two-tier harness architecture — SDK vs Host adapters | ACCEPTED | 2026-04-20 |
| [0002](0002-capability-protocols.md) | Five pluggable capability protocols plus CapabilityResolver | ACCEPTED | 2026-04-20 |
| [0003](0003-ag-ui-transport.md) | Adopt AG-UI as the agent↔user transport protocol | ACCEPTED | 2026-05-21 |
| [0004](0004-test-privacy-boundary.md) | Two-layer public-test / private-persona privacy boundary | ACCEPTED | 2026-04-13 |
| [0005](0005-model-seam-modelref-bindings.md) | One model seam — ModelProvider → ModelRef → per-consumer bindings | ACCEPTED | 2026-07-16 |
| [0006](0006-cross-repo-reuse-policy.md) | Cross-repo reuse policy — share contracts, data, and stateful services; duplicate stateless mechanism | ACCEPTED | 2026-07-16 |
| [0007](0007-meta-harness-posture.md) | Meta-harness posture — integrate under Omnigent, target NemoClaw for the GX10, OpenShell behind the sandbox runner seam | ACCEPTED | 2026-07-17 |

## Adding a new ADR

1. Take the next free number, kebab-case filename:
   `NNNN-short-title.md`.
2. Use the Status / Context / Decision / Consequences sections; date
   the record with the decision date, not the writing date.
3. Cite the originating OpenSpec change
   (`openspec/changes/archive/<date>-<change-id>/`) or
   `docs/architecture-analysis/` document, and the real files that
   embody the decision.
4. Add a row to the index table above.
5. Never edit an ACCEPTED ADR's decision content — write a new ADR
   that supersedes it and link both directions.
