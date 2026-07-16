# graph-client Delta

## ADDED Requirements

### Requirement: Proactive Credential Refresh Method

`GraphClient` SHALL expose an async `refresh_credentials()` method
that acquires a fresh token via
`strategy.acquire_token(scopes, force_refresh=True)` and discards the
returned token — the useful side effects are the strategy's cache
update (and, for the delegated strategy, its on-disk persist). The
method is the transport-level target of the extension lifecycle
`refresh_credentials()` hook.

The existing reactive 401 `invalid_token` single-retry path inside
`_send_with_auth_retry` SHALL remain unchanged and SHALL NOT route
through this method — reactive refresh stays self-contained per the
established D9 behavior; `refresh_credentials()` exists for
proactive/periodic invocation by lifecycle consumers.

#### Scenario: refresh_credentials forces a token refresh

- **WHEN** `await client.refresh_credentials()` is called on a
  `GraphClient` constructed with scopes `["S1"]`
- **THEN** the strategy's `acquire_token` MUST be awaited with those
  scopes and `force_refresh=True`

#### Scenario: 401 retry path is unchanged

- **WHEN** a Graph request returns 401 `invalid_token`
- **THEN** the client MUST perform exactly one
  `force_refresh=True` re-acquisition and replay, per the existing
  "Authentication Token Refresh on 401" requirement, independent of
  any `refresh_credentials()` calls
