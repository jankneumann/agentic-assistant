"""A2A protocol server (P6 `a2a-server`).

Exposes this assistant to external orchestrators (Copilot Studio,
Omnigent-class meta-harnesses) over the A2A agent-to-agent protocol:

- ``types``       — spec-shaped Pydantic models (hand-rolled; see the
                    design note about adopting the official ``a2a-sdk``
                    once it stabilizes)
- ``agent_card``  — AgentCard builder (persona + roles → skills)
- ``task_handler``— SessionRegistry + task lifecycle over
                    ``SdkHarnessAdapter.astream_invoke``
- ``server``      — FastAPI route registration (agent-card GET,
                    JSON-RPC POST /a2a/v1, REST-style
                    POST /a2a/v1/message:stream)

Import direction: ``assistant.a2a`` may import from ``harnesses/`` and
``transports/a2a/``; nothing here imports from ``assistant.web`` (the
web app factory mounts these routes, not the reverse).
"""
