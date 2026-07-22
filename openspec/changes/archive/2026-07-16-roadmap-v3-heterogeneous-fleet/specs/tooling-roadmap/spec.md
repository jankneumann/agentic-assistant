# tooling-roadmap Spec Delta

## MODIFIED Requirements

### Requirement: Provenance Attribution

Every roadmap phase SHALL include columns or annotations indicating its
source — the originating document (e.g., bootstrap-v4.1 P-number,
perplexity feedback § reference, an architecture-review reference under
`docs/architecture-analysis/`, or "new" when none applies) — so that
reviewers can trace each phase back to its motivating analysis. Any
document cited as a provenance source SHALL exist in the repository at
the cited path.

#### Scenario: Phase sourced from perplexity feedback

- **WHEN** a phase's scope is derived from the perplexity review document
- **THEN** the roadmap row SHALL cite the perplexity section in a
  "Perplexity §" column or equivalent annotation
- **AND** `docs/perplexity-feedback.md` SHALL exist in the repository as
  the canonical reference for those citations

#### Scenario: Phase sourced from an architecture review

- **WHEN** a phase's scope is derived from an architecture review
  document (a dated file under `docs/architecture-analysis/`)
- **THEN** the roadmap row SHALL cite that review (and, where
  applicable, its finding identifier — e.g., "arch-review G-A") in its
  Source column
- **AND** the cited review document SHALL exist in the repository as the
  canonical reference for those citations

#### Scenario: Phase carried forward from prior roadmap

- **WHEN** a phase's scope is carried forward from a pre-v3 roadmap
- **THEN** the roadmap row SHALL cite the original P-number (e.g.,
  "original P4") in its Source column
