# Contracts — test-privacy-boundary

No contract sub-types apply to this change. Each was evaluated:

| Sub-type | Applies? | Rationale |
|----------|----------|-----------|
| OpenAPI (`contracts/openapi/`) | No | Change does not add, modify, or remove HTTP endpoints. |
| Database (`contracts/db/`) | No | Change does not add, modify, or remove database schemas or migrations. |
| Events (`contracts/events/`) | No | Change does not add, modify, or remove event types or payloads. |
| Generated types (`contracts/generated/`) | No | No upstream contract to generate from. |

This change is scoped to **test infrastructure, CI configuration, and
documentation**. The boundary between public and private test scopes is
enforced by a `pytest_collection_modifyitems` hook in `tests/conftest.py`
(code-level, in-repo) and by the submodule's own `pyproject.toml` + test
suite (repo-boundary, self-contained). Neither produces an externally
consumable interface that needs a machine-readable contract artifact.

Consuming skills that iterate over `contracts/` should treat a directory
containing only this `README.md` as "no contracts applicable" per the
fallback convention in `/plan-feature` Step 7.
