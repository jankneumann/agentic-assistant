# model-provider Specification (delta)

## ADDED Requirements

### Requirement: Endpoint Health Configuration

The system SHALL accept an optional `health:` block on a persona
`models:` registry entry with keys `path` (probe path appended to the
entry's endpoint, default `/models`), `timeout` (probe timeout in
seconds, default `2.0`), and `ttl` (freshness window of a cached probe
verdict in seconds, default `60`). Registry validation MUST reject a
`health:` block on an entry without a non-empty `endpoint`, unknown
keys inside the block, a `path` not starting with `/`, and
non-positive `timeout`/`ttl` values — each with an actionable error at
persona load. The parsed configuration SHALL be carried on the
resolved `ModelRef` as `health` (`None` when the entry declares no
block). The system SHALL provide an `EndpointHealthMonitor` whose
async `probe`/`refresh` methods issue `GET <endpoint><path>` with the
configured timeout, TLS verification on, and redirects refused,
recording a healthy verdict for a 2xx response and an unhealthy
verdict for any other outcome (including transport errors), stamped
for TTL evaluation.

#### Scenario: Health block parses with defaults

- **WHEN** a registry entry with `endpoint: "http://gx10.local:8000/v1"`
  declares `health: {}`
- **THEN** the resolved `ModelRef.health` MUST carry
  `path="/models"`, `timeout=2.0`, and `ttl=60.0`

#### Scenario: Health on an endpoint-less entry fails load

- **WHEN** a registry entry with no `endpoint` declares `health:`
- **THEN** persona load MUST fail with an error naming the entry and
  stating that health checks require an endpoint

#### Scenario: Probe records the endpoint verdict

- **WHEN** `EndpointHealthMonitor.probe(ref)` is awaited and
  `GET <endpoint><path>` returns HTTP 200
- **THEN** the monitor MUST record a healthy verdict for the entry
- **AND** a subsequent probe receiving a connection error MUST record
  an unhealthy verdict

### Requirement: Health-Filtered Resolution

The system SHALL filter `RegistryModelProvider.resolve` chains by
cached endpoint health *after* required-tag filtering, on both the
binding and tag-resolution paths, consulting only cached state — the
synchronous resolve path MUST NOT issue a network probe. An entry is
skipped only when its cached verdict is unhealthy and younger than its
configured `ttl`; entries without a `health:` block, never-probed
entries, and entries whose verdict has aged past `ttl` remain
eligible. When health filtering empties a chain that satisfied
`required_tags`, `resolve` MUST raise `ModelResolutionError` naming
the unhealthy entries rather than substituting any entry that does not
satisfy the required tags — a request requiring `local-only` or
`private-data-ok` therefore fails closed when no healthy entry carries
those tags, never silently falling back to cloud.

#### Scenario: Unhealthy local entry is skipped in favor of its fallback

- **WHEN** entry `"gx10-chat"` (with `health:`) has a fresh unhealthy
  verdict and declares `fallbacks: ["sonnet"]`
- **AND** `resolve(ModelRequest(consumer="scheduler"))` is called
  against a binding to `"gx10-chat"` with no required tags
- **THEN** the returned chain MUST begin with the `"sonnet"` ModelRef
- **AND** MUST NOT contain `"gx10-chat"`

#### Scenario: Unknown health state stays eligible without probing

- **WHEN** entry `"gx10-chat"` declares `health:` but has never been
  probed
- **AND** `resolve` is called
- **THEN** `"gx10-chat"` MUST appear in the returned chain
- **AND** no network request may be issued during resolution

#### Scenario: Privacy-tagged request fails closed on unhealthy local node

- **WHEN** `resolve(ModelRequest(required_tags=["private-data-ok"]))`
  is called and the only entries carrying `private-data-ok` have fresh
  unhealthy verdicts
- **THEN** a `ModelResolutionError` MUST be raised naming the
  unhealthy entries
- **AND** the provider MUST NOT return any entry lacking
  `private-data-ok`, regardless of its health

#### Scenario: Stale verdict expires back to eligible

- **WHEN** entry `"gx10-chat"` has an unhealthy verdict older than its
  configured `ttl`
- **AND** `resolve` is called
- **THEN** `"gx10-chat"` MUST appear in the returned chain

### Requirement: OpenRouter Catalog Cache

The system SHALL support an optional persona-local model catalog cache
at `<persona_dir>/.cache/models/catalog.json` (git-ignored via the
established `.cache/` convention) written by an explicit sync command
that fetches the OpenRouter `/models` catalog with the http_tools D9
security posture (redirects refused, 10 MiB streaming size cap, TLS
verification, bounded timeouts) and an optional API key resolved
through the persona-scoped `CredentialProvider` (ref
`OPENROUTER_API_KEY`, never logged). The cache SHALL store, per model
`id`, the OpenRouter-shaped `pricing` (verbatim key names),
`context_length`, and normalized `modalities`. At persona load,
registry entries whose `id` matches a cached row MUST inherit
`pricing`, `context_length`, and `modalities` for exactly those fields
they left empty — declared values always win — and a missing or
malformed cache file MUST be a silent no-op: persona load never
touches the network and never fails because of the catalog cache.

#### Scenario: Entry with omitted pricing inherits catalog pricing at load

- **WHEN** the persona's catalog cache holds pricing for id
  `"anthropic/claude-sonnet-4"` and a registry entry declares that
  `id` with no `pricing`
- **THEN** the loaded entry's `ModelRef.pricing` MUST equal the cached
  pricing

#### Scenario: Declared pricing wins over the catalog

- **WHEN** a registry entry declares both an `id` present in the cache
  and its own non-empty `pricing`
- **THEN** the loaded entry's `ModelRef.pricing` MUST equal the
  declared value, not the cached one

#### Scenario: Missing cache is a no-op

- **WHEN** a persona with a `models:` registry has no catalog cache
  file
- **THEN** persona load MUST succeed with all entries exactly as
  declared
- **AND** no network request may be issued

#### Scenario: Sync without network fails clearly

- **WHEN** the catalog sync command runs and the catalog URL is
  unreachable
- **THEN** the command MUST exit non-zero with an error naming the
  transport failure
- **AND** any existing cache file MUST be left unmodified
