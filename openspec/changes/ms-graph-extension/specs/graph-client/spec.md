## ADDED Requirements

### Requirement: CloudGraphClient Protocol

The system SHALL define a `CloudGraphClient` Protocol in
`src/assistant/core/cloud_client.py` declaring the transport-level
interface for any cloud-graph-shaped backend. The Protocol MUST
expose exactly four async methods: `get(path, *, params, headers)`,
`post(path, *, json, params, headers)`, `paginate(path, *, params)`,
and `health_check()`. The Protocol MUST be `@runtime_checkable`.
Future per-cloud implementations (Microsoft Graph in P5, Google APIs
in P14, optionally `msgraph-sdk`-wrapped variants in any future
phase) SHALL satisfy this Protocol.

#### Scenario: Protocol declares four required methods

- **WHEN** the `CloudGraphClient` Protocol is inspected via
  `typing.get_type_hints` / `inspect`
- **THEN** the methods `get`, `post`, `paginate`, `health_check` MUST
  all be declared
- **AND** all four MUST be async (return `Awaitable` or
  `AsyncIterator`)

#### Scenario: Custom GraphClient satisfies Protocol

- **WHEN** `isinstance(GraphClient(extension_name="ms_graph",
  strategy=mock_strategy), CloudGraphClient)` is evaluated
- **THEN** it MUST return `True`

#### Scenario: MockGraphClient satisfies Protocol

- **WHEN** `isinstance(MockGraphClient(), CloudGraphClient)` is
  evaluated
- **THEN** it MUST return `True`

### Requirement: Microsoft Graph Custom Implementation

The system SHALL provide `GraphClient` in
`src/assistant/core/graph_client.py` as a custom httpx-based
implementation of `CloudGraphClient` for Microsoft Graph
(`https://graph.microsoft.com/v1.0/`). The class SHALL accept an
`extension_name` and an `MSALStrategy` instance at construction.
Every outbound HTTP request SHALL acquire a fresh token via the
strategy's `acquire_token(scopes)` and attach it as
`Authorization: Bearer <token>`.

#### Scenario: Constructor stores extension_name and strategy

- **WHEN** `GraphClient(extension_name="outlook", strategy=mock_strategy,
  scopes=["Mail.Read"])` is constructed
- **THEN** the instance MUST expose `self.extension_name == "outlook"`
- **AND** `self._strategy` MUST hold the provided strategy

#### Scenario: GET request attaches Authorization Bearer header

- **WHEN** `await client.get("/me/messages")` is called
- **AND** the strategy's `acquire_token` returns the string
  `MOCK_TOKEN_VALUE`
- **THEN** the outbound httpx request MUST include header
  `Authorization: Bearer MOCK_TOKEN_VALUE`

#### Scenario: GET request returns parsed JSON body

- **WHEN** the Graph endpoint returns HTTP 200 with body `{"value": [{
  "id": "1"}]}`
- **AND** `await client.get("/me/messages")` is awaited
- **THEN** the returned value MUST equal `{"value": [{"id": "1"}]}`

#### Scenario: POST request sends JSON body and returns parsed response

- **WHEN** `await client.post("/me/sendMail", json={"message": {
  "subject": "x"}})` is called
- **THEN** the outbound httpx request MUST be `Content-Type:
  application/json`
- **AND** the request body MUST equal the JSON-encoded form of the
  provided `json` parameter
- **AND** the response body MUST be returned as a parsed dict

### Requirement: OData Pagination

The system SHALL implement `paginate(path, *, params)` to chase
`@odata.nextLink` URLs returned by the Microsoft Graph API. Each
yielded item SHALL be the full page response (a dict with `value`,
`@odata.nextLink`, and other top-level keys). The implementation
SHALL stop when no `@odata.nextLink` is present and SHALL enforce a
hard ceiling (default 100 pages, configurable at construction).

#### Scenario: Paginate yields successive pages until nextLink absent

- **WHEN** the Graph API returns page 1 with
  `@odata.nextLink="https://graph.microsoft.com/v1.0/me/messages?$skip=25"`
  and page 2 without `@odata.nextLink`
- **AND** `[page async for page in client.paginate("/me/messages")]`
  is collected
- **THEN** the list MUST contain exactly two pages
- **AND** the second page MUST be the page without `@odata.nextLink`

#### Scenario: nextLink chase preserves header and base URL

- **WHEN** page 1 returns `@odata.nextLink="https://graph.microsoft.com
  /v1.0/me/messages?$skip=25"`
- **AND** the client follows the link
- **THEN** the second request MUST be a GET to the absolute URL from
  `@odata.nextLink`
- **AND** the `Authorization: Bearer` header MUST be attached to the
  second request as well

#### Scenario: Page ceiling triggers termination with warning

- **WHEN** the Graph API returns 101 consecutive pages, each with a
  non-empty `@odata.nextLink`
- **AND** the client's page ceiling is the default (100)
- **THEN** iteration MUST stop after exactly 100 pages
- **AND** a warning log entry MUST be emitted naming the path that hit
  the ceiling

### Requirement: Resilience Integration via Per-Extension Breaker Key

The system SHALL wrap every outbound `GraphClient` HTTP call with the
P9 `@resilient_http(breaker_key=f"graph:{self.extension_name}")`
decorator. Each extension's instance of `GraphClient` SHALL have its
own breaker key namespace so that a failing extension does not trip
the breaker for unrelated extensions.

#### Scenario: Breaker key derived from extension_name

- **WHEN** `GraphClient(extension_name="teams", ...)` is constructed
- **AND** an outbound HTTP call is made
- **THEN** the call MUST be wrapped with `@resilient_http(breaker_key
  ="graph:teams")`
- **AND** `CircuitBreakerRegistry.get_breaker("graph:teams")` MUST be
  the breaker instance recording success/failure

#### Scenario: Breaker open on one extension does not affect another

- **WHEN** the breaker for `graph:outlook` is in OPEN state
- **AND** `GraphClient(extension_name="teams", ...)` issues a call
- **THEN** the call MUST proceed through the `graph:teams` breaker
  (which may be CLOSED or HALF_OPEN)
- **AND** the OPEN state of `graph:outlook` MUST NOT short-circuit
  the `graph:teams` call

### Requirement: Authentication Token Refresh on 401

The system SHALL detect HTTP 401 responses with
`WWW-Authenticate: Bearer error="invalid_token"` and attempt exactly
one token refresh by calling `strategy.acquire_token(scopes,
force_refresh=True)`. If the retry succeeds, the original request
SHALL be replayed once with the refreshed token. If the retry fails
or returns 401 again, `MSALAuthenticationError` SHALL propagate.

#### Scenario: 401 response triggers force_refresh and retry

- **WHEN** the first GET to `/me/messages` returns 401 with
  `WWW-Authenticate: Bearer error="invalid_token"`
- **AND** `strategy.acquire_token(scopes, force_refresh=True)` returns
  a new token
- **AND** the replayed request returns 200
- **THEN** the caller MUST receive the 200 response body
- **AND** exactly two outbound requests MUST be made

#### Scenario: Second 401 propagates as MSALAuthenticationError

- **WHEN** the first GET returns 401 invalid_token
- **AND** the replayed GET (with force_refresh token) also returns 401
- **THEN** `MSALAuthenticationError` MUST be raised
- **AND** no further retry MUST be attempted

### Requirement: Error Sanitization on GraphAPIError

The system SHALL raise `GraphAPIError` for any non-2xx Graph response.
The error type SHALL expose `status_code: int`, `error_code: str |
None`, `request_id: str | None`, and `message: str`. The error's
`__str__` representation SHALL be passed through P9's
`_sanitize_error_string` helper before logging or raising so that
access tokens, refresh tokens, and other secret-shaped substrings are
redacted.

#### Scenario: Non-2xx response raises GraphAPIError with status_code

- **WHEN** the Graph API returns HTTP 403 with body
  `{"error": {"code": "Authorization_RequestDenied"}}`
- **AND** the request is made via `client.get`
- **THEN** `GraphAPIError` MUST be raised
- **AND** `error.status_code` MUST equal 403
- **AND** `error.error_code` MUST equal `"Authorization_RequestDenied"`

#### Scenario: Authorization header value is sanitized in error string

- **WHEN** an error message somehow contains the substring
  `Authorization: Bearer eyJ0eXAi...` (a JWT-shaped sequence)
- **AND** `str(GraphAPIError(message=...))` is computed
- **THEN** the rendered string MUST NOT contain the JWT value
- **AND** the JWT MUST be replaced with `[REDACTED]` per the
  `_sanitize_error_string` rules

### Requirement: Health Check Reports Breaker State

The system SHALL implement `GraphClient.health_check()` to return a
`HealthStatus` derived from the per-extension circuit breaker. The
state mapping SHALL follow `error-resilience`'s
`health_status_from_breaker` helper.

#### Scenario: CLOSED breaker yields OK HealthStatus

- **WHEN** the breaker for `graph:outlook` is CLOSED with no recent
  failures
- **AND** `GraphClient(extension_name="outlook").health_check()` is
  awaited
- **THEN** the returned `HealthStatus.state` MUST equal `HealthState.OK`
- **AND** `breaker_key` MUST equal `"graph:outlook"`

#### Scenario: OPEN breaker yields UNAVAILABLE HealthStatus

- **WHEN** the breaker for `graph:outlook` is OPEN
- **AND** `health_check()` is awaited
- **THEN** the returned `HealthStatus.state` MUST equal
  `HealthState.UNAVAILABLE`
