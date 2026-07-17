# a2a-server Specification (delta)

## MODIFIED Requirements

### Requirement: Agent Card Discovery

The system SHALL serve an A2A agent card describing the bound persona
at `GET /.well-known/agent-card.json` (canonical, A2A protocol version
0.3.0) and at `GET /.well-known/agent.json` (legacy pre-0.3.0 alias),
returning identical JSON at both paths. The card MUST declare
`protocolVersion`, `name` (persona display name), `description`,
`url` (the served base URL plus the JSON-RPC mount `/a2a/v1`),
`version`, `capabilities.streaming = true`, and one skill per role
enabled for the persona — skill `id` equal to the role name, skill
`name` equal to the role display name, and the role description. Wire
field names MUST be camelCase per the A2A schema. When the persona
declares `auth.a2a` (P25 agent-iam), the card MUST additionally
advertise the enforced scheme via `securitySchemes` (an OpenAPI-style
HTTP bearer scheme object, `{type: http, scheme: bearer}`) and a
matching `security` requirement list; without a declaration both
fields MUST be omitted. The card MUST never carry the token value or
its credential ref, and the card routes MUST remain readable without
authentication — the card is how clients discover the required
scheme.

#### Scenario: Card served at both well-known paths

- **WHEN** a client GETs `/.well-known/agent-card.json` and
  `/.well-known/agent.json` against a server started with `--a2a`
- **THEN** both responses MUST be HTTP 200 with identical JSON bodies

#### Scenario: Roles are exposed as skills

- **WHEN** the persona has roles `coder` and `researcher` enabled
- **THEN** the card's `skills` array MUST contain exactly one entry
  per role with `id` equal to the role name
- **AND** `capabilities.streaming` MUST be `true`

#### Scenario: Card advertises the bearer scheme when auth is declared

- **WHEN** the persona declares `auth.a2a: {type: bearer, token_env:
  A2A_TOKEN}`
- **THEN** the card MUST carry `securitySchemes` with an HTTP bearer
  scheme and `security == [{"bearer": []}]`
- **AND** the card MUST be served without authentication
- **AND** neither the token value nor `A2A_TOKEN` MUST appear
  anywhere on the card

#### Scenario: Unauthenticated card omits security fields

- **WHEN** the persona declares no `auth.a2a`
- **THEN** the card JSON MUST contain neither `securitySchemes` nor
  `security`

## ADDED Requirements

### Requirement: Inbound Bearer Authentication

The system SHALL enforce inbound bearer-token authentication on the
A2A message routes (`POST /a2a/v1` and `POST /a2a/v1/message:stream`)
when the persona declares `auth.a2a: {type: bearer, token_env:
<ref>}`. The expected token SHALL resolve through the persona's
`CredentialProvider` (never raw `os.environ`) at server-state build
time; a declared-but-empty resolution MUST fail startup with an
actionable error (declared auth must never silently disable). A
request without a valid `Authorization: Bearer <token>` header —
missing, wrong scheme, or wrong token, compared in constant time —
MUST be rejected with HTTP 401 and a `WWW-Authenticate: Bearer`
challenge BEFORE any protocol handling (an HTTP-level failure, not a
JSON-RPC error envelope). Without an `auth.a2a` declaration the
surface SHALL keep its loopback-unauthenticated behavior and the
server MUST log a startup WARNING naming the posture. The resolved
token MUST be excluded from the server state's repr.

#### Scenario: Missing token is rejected with a challenge

- **WHEN** auth is configured and a client POSTs to `/a2a/v1` without
  an `Authorization` header
- **THEN** the response MUST be HTTP 401 with a
  `WWW-Authenticate: Bearer` header
- **AND** the body MUST NOT be a JSON-RPC envelope

#### Scenario: Wrong token or scheme is rejected

- **WHEN** auth is configured and the client presents
  `Authorization: Bearer wrong` (or a non-bearer scheme)
- **THEN** the response MUST be HTTP 401

#### Scenario: Valid token reaches protocol handling

- **WHEN** auth is configured and the client presents the correct
  bearer token on `message/send`
- **THEN** the request MUST be processed normally (HTTP 200 with a
  task result)
- **AND** the REST-style stream alias MUST enforce the same token

#### Scenario: Unconfigured auth warns and stays open

- **WHEN** the persona declares no `auth.a2a`
- **THEN** requests without credentials MUST succeed as before
- **AND** a startup WARNING MUST name the unauthenticated posture

#### Scenario: Declared but unresolvable token fails startup

- **WHEN** the persona declares `auth.a2a` with a `token_env` that
  resolves empty
- **THEN** building the A2A server state MUST raise an error naming
  the ref
