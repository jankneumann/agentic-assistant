# cli-interface Specification (delta)

## MODIFIED Requirements

### Requirement: CLI serve Subcommand

The CLI SHALL provide a `serve` subcommand that mounts a FastAPI ASGI
application binding a single persona and role for the lifetime of the
server process. The subcommand SHALL accept `-p/--persona` (required),
`-r/--role` (optional, defaulting to the persona's `default_role`),
`-H/--harness` (optional, defaulting to `deep_agents`), `--host`
(optional, defaulting to `127.0.0.1`), `--port` (optional,
defaulting to `8765`), `--a2a` (optional flag, default off), and
`--mcp` (optional flag, default off). The server SHALL block until
interrupted; the exit code on `Ctrl-C` SHALL be 0. When `--a2a` is
passed, the app factory MUST be invoked with `enable_a2a=True` and
`a2a_base_url="http://<host>:<port>"` so the A2A protocol surface
(agent card + `POST /a2a/v1`) is mounted alongside the AG-UI routes
on the same server. When `--mcp` is passed, the app factory MUST be
invoked with `enable_mcp=True` so the MCP streamable-HTTP surface is
mounted at `/mcp` on the same server, and the startup output MUST
name the `/mcp` endpoint. The two flags SHALL compose. When neither
flag is present the app factory MUST be called with the legacy
`make_app(persona, role, harness)` shape and no A2A or MCP routes
registered.

#### Scenario: serve binds the supplied persona and role at startup

- **WHEN** `assistant serve -p personal -r teacher --port 8001` is
  executed
- **THEN** the FastAPI app's lifespan MUST construct a single harness
  instance with persona `personal` and role `teacher`
- **AND** the constructed harness MUST be stored on `app.state.harness`
  before the server accepts requests

#### Scenario: serve defaults host to 127.0.0.1

- **WHEN** `assistant serve -p personal` is executed without `--host`
- **THEN** the underlying uvicorn server MUST bind to `127.0.0.1`,
  not `0.0.0.0`

#### Scenario: serve --a2a mounts the A2A surface

- **WHEN** `assistant serve -p personal --a2a --port 9001` is executed
- **THEN** the app factory MUST receive `enable_a2a=True` and
  `a2a_base_url="http://127.0.0.1:9001"`
- **AND** the startup output MUST name the agent-card URL

#### Scenario: serve --mcp mounts the MCP surface

- **WHEN** `assistant serve -p personal --mcp --port 9002` is executed
- **THEN** the app factory MUST receive `enable_mcp=True`
- **AND** the startup output MUST name the `/mcp` endpoint

#### Scenario: serve --a2a --mcp composes both surfaces

- **WHEN** `assistant serve -p personal --a2a --mcp` is executed
- **THEN** the app factory MUST receive `enable_a2a=True`,
  `a2a_base_url`, and `enable_mcp=True` in the same call

#### Scenario: serve without flags keeps the legacy surface

- **WHEN** `assistant serve -p personal -r coder` is executed without
  `--a2a` or `--mcp`
- **THEN** the app factory MUST be called without A2A or MCP keyword
  arguments
- **AND** requests to `/.well-known/agent-card.json`, `/a2a/v1`, and
  `/mcp` MUST return 404
