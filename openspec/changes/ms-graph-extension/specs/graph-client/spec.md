## ADDED Requirements

### Requirement: CloudGraphClient Protocol

The system SHALL define a `CloudGraphClient` Protocol in
`src/assistant/core/cloud_client.py` declaring the transport-level
interface for any cloud-graph-shaped backend. The Protocol MUST
expose exactly five async methods:
`get(path, *, params, headers)`,
`post(path, *, json, params, headers, retry_safe=True)`,
`paginate(path, *, params)`,
`get_bytes(path, *, params, headers, max_bytes)`,
and `health_check()`. The Protocol MUST be `@runtime_checkable`.
Future per-cloud implementations (Microsoft Graph in P5, Google APIs
in P14, optionally `msgraph-sdk`-wrapped variants in any future
phase) SHALL satisfy this Protocol.

#### Scenario: Protocol declares five required methods

- **WHEN** the `CloudGraphClient` Protocol is inspected via
  `typing.get_type_hints` / `inspect`
- **THEN** the methods `get`, `post`, `paginate`, `get_bytes`,
  `health_check` MUST all be declared
- **AND** all five MUST be async (return `Awaitable` or
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

#### Scenario: Page ceiling raises (see Pagination Page Ceiling requirement)

- **WHEN** the configured page ceiling is exceeded
- **THEN** see the requirement "Pagination Page Ceiling Raises
  Instead of Truncating" below for the authoritative behavior

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

### Requirement: Retry-After Honoring on 429 and 503

The system SHALL parse the `Retry-After` response header on HTTP 429
(Too Many Requests) and 503 (Service Unavailable) responses from
Microsoft Graph. When present, `GraphClient` SHALL delay the next
retry attempt by at least the value indicated by the header before
allowing the underlying `@resilient_http` policy to backoff further.
Both numeric (delta-seconds) and HTTP-date forms of `Retry-After`
SHALL be supported. This requirement supersedes generic exponential
backoff for these specific status codes when the header is present.

#### Scenario: 429 with delta-seconds Retry-After delays retry

- **WHEN** the Graph API returns HTTP 429 with header
  `Retry-After: 5`
- **AND** the request was made via `GraphClient.get`
- **THEN** the client MUST wait at least 5 seconds before the next
  attempt
- **AND** the wait MUST occur regardless of P9 backoff timing

#### Scenario: 503 with HTTP-date Retry-After delays retry

- **WHEN** the Graph API returns HTTP 503 with header
  `Retry-After: Wed, 21 Oct 2026 07:28:00 GMT`
- **AND** the date is in the future relative to the current clock
- **THEN** the client MUST wait until the indicated time before the
  next attempt

#### Scenario: 429 without Retry-After falls through to default backoff

- **WHEN** the Graph API returns HTTP 429 without a `Retry-After`
  header
- **THEN** the client MUST use the default P9 exponential backoff
  policy unchanged

#### Scenario: Past HTTP-date Retry-After falls through to default backoff

- **WHEN** the Graph API returns HTTP 503 with header
  `Retry-After: Wed, 21 Oct 2020 07:28:00 GMT` (a date strictly in
  the past relative to the current clock)
- **THEN** the client MUST NOT block waiting for the past time
- **AND** the client MUST fall through to the default P9 exponential
  backoff policy unchanged

#### Scenario: Malformed Retry-After is logged and ignored

- **WHEN** the Graph API returns HTTP 429 with header
  `Retry-After: not-a-number-or-date`
- **THEN** the client MUST log a structured warning identifying the
  malformed header value (with the value sanitized to a bounded
  length to prevent log injection)
- **AND** the client MUST fall through to the default P9 exponential
  backoff policy unchanged
- **AND** the client MUST NOT raise on the malformed header alone

### Requirement: Per-Request Timeout Configuration

The system SHALL configure the underlying `httpx.AsyncClient` with
explicit timeouts. The default SHALL be a `httpx.Timeout` with
`connect=10.0`, `read=30.0`, `write=30.0`, and `pool=5.0` seconds.
The timeout SHALL be overridable via `GraphClient(timeout=...)`
constructor argument. A request that exceeds any of these timeouts
SHALL raise `GraphAPIError` with `status_code=None` and a message
identifying which timeout was exceeded.

#### Scenario: Default timeout values applied

- **WHEN** `GraphClient(extension_name="outlook", strategy=mock)` is
  constructed without a `timeout` argument
- **THEN** the underlying `httpx.AsyncClient.timeout` MUST equal
  `httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=5.0)`

#### Scenario: Read timeout raises GraphAPIError

- **WHEN** an outbound GET request takes longer than the configured
  `read` timeout
- **THEN** `GraphAPIError` MUST be raised
- **AND** `error.status_code` MUST be `None`
- **AND** `error.message` MUST contain the substring `"read timeout"`

### Requirement: Transport-Level Observability Span per Request

The system SHALL emit one observability span per outbound GraphClient
HTTP request via the P4 observability provider, using
`get_observability_provider().trace_graph_call(...)` (a new method
on the observability provider, registered in this change). The span
MUST include `extension_name`, `method` (GET/POST/etc.), normalized
`path` (with sensitive values like `message_id` redacted to
`{message_id}` placeholders), `status_code`, `duration_ms`, the
Microsoft Graph response header `request-id` when present, retry
attempt count, and `breaker_key`. The span MUST NOT include token
values, full request bodies, or query parameter values that may
contain PII.

#### Scenario: Successful GET emits one trace_graph_call span

- **WHEN** `await client.get("/me/messages")` succeeds with HTTP 200
  and response header `request-id: abc123`
- **THEN** `get_observability_provider().trace_graph_call` MUST be
  called exactly once
- **AND** the call kwargs MUST include `extension_name="outlook"`
  (or whichever was passed at construction), `method="GET"`,
  `path="/me/messages"`, `status_code=200`, `request_id="abc123"`,
  and a non-negative `duration_ms`

#### Scenario: 401-then-success emits two spans (one per attempt)

- **WHEN** the first GET returns 401 invalid_token, force_refresh
  acquires a new token, and the replay returns 200
- **THEN** `trace_graph_call` MUST be called exactly twice
- **AND** the first span's `status_code` MUST equal 401, the
  second's `status_code` MUST equal 200
- **AND** each span's `attempt` MUST reflect its position in the
  sequence (1, 2)

#### Scenario: Path normalization redacts message_id-shaped segments

- **WHEN** `await client.get("/me/messages/AAMkAGI...long-id-here")`
  is called
- **THEN** the emitted span's `path` MUST equal
  `"/me/messages/{message_id}"`
- **AND** the long ID MUST NOT appear anywhere in the span payload

### Requirement: Empty-Body Handling for 202 and 204 Responses

The system SHALL treat HTTP 202 (Accepted) and 204 (No Content)
responses as successful and SHALL return an empty `dict[str, Any]`
(`{}`) from `GraphClient.post()` and `GraphClient.get()` in such
cases without attempting JSON parsing. Microsoft Graph routinely
returns 202 with empty body on successful POST requests to write
endpoints (`/me/sendMail`, `/chats/{id}/messages` for some channel
types, etc).

#### Scenario: 202 empty body returns empty dict

- **WHEN** `await client.post("/me/sendMail", json={...})` is called
- **AND** the Graph API returns HTTP 202 with `Content-Length: 0`
- **THEN** the call MUST return `{}`
- **AND** no exception MUST be raised

#### Scenario: 204 empty body returns empty dict

- **WHEN** the Graph API returns HTTP 204 with no body
- **THEN** `GraphClient` methods MUST return `{}`
- **AND** no exception MUST be raised

#### Scenario: 200 with empty JSON-Content-Type body returns empty dict

- **WHEN** the Graph API returns HTTP 200 with
  `Content-Type: application/json` but a zero-length body
- **THEN** `GraphClient` methods MUST return `{}` rather than raising
  a JSON parse error

### Requirement: GraphAPIError Subclasses httpx.HTTPStatusError

The system SHALL define `GraphAPIError` as a subclass of
`httpx.HTTPStatusError` so that the P9 `@resilient_http` decorator
recognizes Graph errors and applies its standard retry classification
(retry on 408/425/429/5xx + timeout exceptions; fail-fast on
4xx-other). Without this subclass relationship, P9's classifier would
not match Graph errors and retries would silently never fire.

#### Scenario: GraphAPIError is an httpx.HTTPStatusError

- **WHEN** a `GraphAPIError` instance is constructed
- **THEN** `isinstance(err, httpx.HTTPStatusError)` MUST be `True`
- **AND** `err.response.status_code` MUST equal the Graph status code

#### Scenario: 5xx GraphAPIError triggers P9 retry

- **WHEN** the Graph API returns HTTP 502
- **AND** `GraphClient.get` is wrapped with `@resilient_http`
- **THEN** P9 MUST classify the raised `GraphAPIError` as retriable
- **AND** at least one retry attempt MUST occur

### Requirement: Per-Method Retry Safety Control

The system SHALL expose a `retry_safe: bool = True` parameter on
`GraphClient.post()` (and on the `CloudGraphClient.post` Protocol).
When `retry_safe=False`, the call SHALL bypass the
`@resilient_http` retry layer (via a separate non-retrying
implementation path) so that non-idempotent writes are never
auto-replayed by the resilience layer. Tools that perform
non-idempotent writes (`outlook.send_email`,
`teams.post_chat_message`) SHALL pass `retry_safe=False`. Idempotent
operations MAY rely on the default `retry_safe=True`.

#### Scenario: retry_safe=False bypasses P9 retry

- **WHEN** `await client.post("/me/sendMail", json={...},
  retry_safe=False)` is called
- **AND** the first attempt returns HTTP 503
- **THEN** `GraphAPIError` MUST be raised on the first attempt
- **AND** no retry MUST be made
- **AND** the breaker MUST still record the failure

#### Scenario: retry_safe=True (default) retries on 5xx

- **WHEN** `await client.post("/me/messages", json={...})` is called
  without specifying `retry_safe`
- **AND** the first attempt returns HTTP 502
- **THEN** at least one retry attempt MUST be made before the call
  returns or raises

### Requirement: Binary Download via get_bytes

The system SHALL implement `get_bytes(path, *, params=None,
headers=None, max_bytes=52428800)` (default 50 MiB ceiling) on
`GraphClient` to retrieve binary content from Microsoft Graph
endpoints that return non-JSON payloads (`/sites/{id}/drive/root:/<path>:/content`,
`/me/drive/items/{id}/content`, etc). The implementation SHALL
stream the response body and SHALL abort with `GraphAPIError`
(status_code=None, error_code="size_exceeded") if the cumulative
read exceeds `max_bytes`. The response SHALL be buffered to a
temporary file path returned in a result dict, not returned as raw
bytes in memory, so that LLM tool serialization stays bounded.

The result dict SHALL have shape:

```python
{
    "path": "/tmp/<random>.bin",   # absolute path to downloaded content
    "size_bytes": 12345,            # actual bytes written
    "content_type": "application/pdf",  # from response Content-Type
    "request_id": "abc123",         # for correlation
}
```

The caller is responsible for cleaning up the tempfile after
processing.

#### Scenario: Successful download returns path + metadata dict

- **WHEN** `await client.get_bytes("/me/drive/items/abc/content")` is
  called
- **AND** the Graph API returns HTTP 200 with body of 12345 bytes and
  `Content-Type: application/pdf`
- **THEN** the returned dict MUST contain the keys `path`,
  `size_bytes`, `content_type`, `request_id`
- **AND** `os.path.exists(result["path"])` MUST be `True`
- **AND** `os.path.getsize(result["path"])` MUST equal 12345
- **AND** `result["content_type"]` MUST equal `"application/pdf"`

#### Scenario: Download exceeding max_bytes aborts with size_exceeded

- **WHEN** `await client.get_bytes("/path", max_bytes=1024)` is called
- **AND** the Graph API begins streaming a body larger than 1024 bytes
- **THEN** the read MUST abort once cumulative bytes exceed 1024
- **AND** `GraphAPIError` MUST be raised with
  `error_code="size_exceeded"`
- **AND** any partial file written MUST be deleted before the error
  is raised

#### Scenario: get_bytes wraps with same resilience and observability layers

- **WHEN** `await client.get_bytes(...)` is called
- **THEN** `@resilient_http(breaker_key=f"graph:{extension_name}")`
  MUST wrap the call
- **AND** `trace_graph_call` MUST emit one span with `method="GET"`
  and a `bytes_streamed` field on success

### Requirement: Pagination Page Ceiling Raises Instead of Truncating

The system SHALL raise `GraphAPIError` with
`error_code="page_ceiling_exceeded"` when `paginate()` reaches the
configured page ceiling without exhausting `@odata.nextLink`. Silent
truncation (yielding the last page and stopping) is forbidden because
callers cannot distinguish a complete result from a truncated one. A
warning log entry SHALL still be emitted before the exception is
raised, naming the path that hit the ceiling.

This requirement supersedes the prior "Page ceiling triggers
termination with warning" scenario semantics.

#### Scenario: Page ceiling raises rather than terminates silently

- **WHEN** the Graph API returns 101 consecutive pages, each with a
  non-empty `@odata.nextLink`
- **AND** the client's page ceiling is the default (100)
- **THEN** iteration MUST yield the first 100 pages
- **AND** the iteration MUST raise `GraphAPIError` with
  `error_code="page_ceiling_exceeded"` rather than returning
  silently
- **AND** a warning log MUST be emitted naming the path before the
  exception

#### Scenario: Page ceiling is configurable

- **WHEN** `GraphClient(extension_name="outlook", page_ceiling=500)`
  is constructed
- **AND** `paginate()` is called against an endpoint returning 600
  pages
- **THEN** iteration MUST yield 500 pages and raise on the 501st
  request

### Requirement: HTTP Client Lifecycle and Resource Cleanup

The system SHALL ensure that the underlying `httpx.AsyncClient` owned
by `GraphClient` is deterministically closed. `GraphClient` SHALL
implement async context-manager methods `__aenter__` and `__aexit__`
that, on exit, await the underlying `AsyncClient.aclose()`. Until the
P10 extension lifecycle hooks land, every construction site
(`PersonaRegistry.load_extensions` and tests) MUST construct
`GraphClient` inside an `async with` block or otherwise guarantee
that `aclose()` is awaited before process exit. `GraphClient` SHALL
also expose an explicit `async def aclose(self) -> None` method for
callers that cannot use context managers (e.g., factory-style
construction in P5; superseded by P10).

#### Scenario: Async context-manager closes the underlying httpx client

- **WHEN** `async with GraphClient(extension_name="outlook",
  strategy=mock) as client: pass` is executed
- **THEN** at exit, `httpx.AsyncClient.aclose` MUST have been awaited
  exactly once
- **AND** subsequent calls on the closed `client` MUST raise (httpx
  raises `RuntimeError`-derived errors on closed clients)

#### Scenario: Explicit aclose closes the underlying httpx client

- **WHEN** `client = GraphClient(...)` is constructed and
  `await client.aclose()` is awaited
- **THEN** `httpx.AsyncClient.aclose` MUST have been awaited exactly
  once

### Requirement: Cross-Domain Redirect Rejection

The system SHALL reject any pagination `@odata.nextLink` URL or HTTP
3xx redirect target whose host is not within the trusted Graph API
domain (`https://graph.microsoft.com/` and its national-cloud
variants `graph.microsoft.us`, `graph.microsoft.de`,
`microsoftgraph.chinacloudapi.cn` per Microsoft's documented sovereign
cloud endpoints). Rejection MUST occur **before** the bearer token is
attached to the redirected request, so a malicious or
misconfigured redirect cannot capture the access token. The trusted
host set SHALL be a configurable list passed at `GraphClient`
construction (`trusted_hosts: list[str] | None = None`); the default
SHALL be the four documented Graph hosts above.

The underlying `httpx.AsyncClient` SHALL be configured with
`follow_redirects=False`. When pagination `@odata.nextLink` carries a
non-trusted host, `paginate()` MUST raise `GraphAPIError` with
`error_code="invalid_redirect"` and message identifying the rejected
host without echoing query parameters.

#### Scenario: Pagination nextLink to graph.microsoft.com is followed

- **WHEN** the Graph API returns a page with
  `@odata.nextLink: "https://graph.microsoft.com/v1.0/me/messages?$skip=10"`
- **THEN** `paginate()` MUST follow the link and yield the next page

#### Scenario: Pagination nextLink to non-trusted host is rejected

- **WHEN** the Graph API returns a page with
  `@odata.nextLink: "https://attacker.example.com/exfiltrate?token=..."`
- **THEN** `paginate()` MUST NOT issue the redirected request
- **AND** `GraphAPIError` MUST be raised with
  `error_code="invalid_redirect"`
- **AND** the bearer token MUST NOT have been transmitted to
  `attacker.example.com`

#### Scenario: HTTP 3xx response is not auto-followed

- **WHEN** the Graph API returns a 302 response with
  `Location: https://attacker.example.com/`
- **THEN** the client MUST NOT follow the redirect
- **AND** the response MUST surface as the original 302 (not as a
  follow-up GET to the redirect target)
- **AND** the bearer token MUST NOT have been transmitted to the
  redirect target
