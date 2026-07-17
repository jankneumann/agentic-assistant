"""Opt-in smoke test for ContainerSandboxProvider with a REAL runtime.

CI never runs this — the default pytest sweep only exercises the
mocked-runner unit tests (tests/test_sandbox_container.py). On a
machine with docker or podman installed, run:

    RUN_CONTAINER_SANDBOX_TESTS=1 uv run pytest \
        tests/integration/test_container_sandbox_smoke.py -v

Requires the ``python:3.12-slim`` image (or pre-pull any small image
and set ``SANDBOX_SMOKE_IMAGE``).
"""

from __future__ import annotations

import os

import pytest

from assistant.core.capabilities.sandbox import (
    ContainerSandboxProvider,
    SandboxedProcessRunner,
    detect_container_runtime,
)
from assistant.core.capabilities.types import NetworkPlane, SandboxConfig

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_CONTAINER_SANDBOX_TESTS") != "1"
    or detect_container_runtime() is None,
    reason=(
        "set RUN_CONTAINER_SANDBOX_TESTS=1 (and install docker/podman) "
        "to run real container sandbox smoke tests"
    ),
)


def test_echo_runs_inside_container_with_no_network() -> None:
    image = os.environ.get("SANDBOX_SMOKE_IMAGE", "python:3.12-slim")
    provider = ContainerSandboxProvider(image=image)
    config = SandboxConfig(network=NetworkPlane(allow=()))
    context = provider.create_context(config)
    try:
        runner = SandboxedProcessRunner(provider, config, context)
        result = runner.run(["echo", "sandbox-ok"])
        assert result.returncode == 0, result.stderr
        assert "sandbox-ok" in result.stdout
    finally:
        provider.cleanup(context)
