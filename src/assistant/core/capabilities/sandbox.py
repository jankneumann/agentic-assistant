"""SandboxProvider protocol and PassthroughSandbox stub — Task 1.6."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from assistant.core.capabilities.types import ExecutionContext, SandboxConfig


@runtime_checkable
class SandboxProvider(Protocol):
    def create_context(self, config: SandboxConfig) -> ExecutionContext: ...
    def cleanup(self, context: ExecutionContext) -> None: ...


class PassthroughSandbox:
    def create_context(self, config: SandboxConfig) -> ExecutionContext:
        return ExecutionContext(work_dir=Path.cwd(), isolation_type="none")

    def cleanup(self, context: ExecutionContext) -> None:
        pass
