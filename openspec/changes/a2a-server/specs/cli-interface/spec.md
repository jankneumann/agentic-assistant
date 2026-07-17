# cli-interface Specification (delta)

## MODIFIED Requirements

### Requirement: CLI serve Subcommand

The CLI SHALL provide a `serve` subcommand that mounts a FastAPI ASGI
application binding a single persona and role for the lifetime of the
server process. The subcommand SHALL accept `-p/--persona` (required),
`-r/--role` (optional, defaulting to the persona's `default_role`),
`-H/--harness` (optional, defaulting to `deep_agents`), `--host`
(optional, defaulting to `127.0.0.1`), `--port` (optional,
defaulting to `8765`), and `--a2a` (optional flag, default off). The
server SHALL block until interrupted; the exit code on `Ctrl-C` SHALL
be 0. When `--a2a` is passed, the app factory MUST be invoked with
`enable_a2a=True` and `a2a_base_url="http://<host>:<port>"` so the A2A
protocol surface (agent card + `POST /a2a/v1`) is mounted alongside
the AG-UI routes on the same server; when the flag is absent the app
factory MUST be called with the legacy
`make_app(persona, role, harness)` shape and no A2A routes registered.

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

#### Scenario: serve without --a2a keeps the legacy surface

- **WHEN** `assistant serve -p personal -r coder` is executed without
  `--a2a`
- **THEN** the app factory MUST be called without A2A keyword
  arguments
- **AND** requests to `/.well-known/agent-card.json` and `/a2a/v1`
  MUST return 404
