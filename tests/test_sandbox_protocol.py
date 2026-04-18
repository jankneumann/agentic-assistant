"""Tests for SandboxProvider protocol — Task 1.5.

Covers: protocol conformance, PassthroughSandbox stub behavior.
"""

from __future__ import annotations

from pathlib import Path


def test_stub_satisfies_protocol() -> None:
    from assistant.core.capabilities.sandbox import PassthroughSandbox, SandboxProvider

    assert isinstance(PassthroughSandbox(), SandboxProvider)


def test_stub_returns_current_directory() -> None:
    from assistant.core.capabilities.sandbox import PassthroughSandbox
    from assistant.core.capabilities.types import SandboxConfig

    stub = PassthroughSandbox()
    ctx = stub.create_context(SandboxConfig())
    assert ctx.work_dir == Path.cwd()
    assert ctx.isolation_type == "none"


def test_stub_cleanup_is_safe() -> None:
    from assistant.core.capabilities.sandbox import PassthroughSandbox
    from assistant.core.capabilities.types import ExecutionContext

    stub = PassthroughSandbox()
    ctx = ExecutionContext(work_dir=Path("/tmp"), isolation_type="none")
    stub.cleanup(ctx)
