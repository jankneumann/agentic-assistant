"""AG-UI transport layer: maps HarnessEvent streams to AG-UI protocol events.

Public API is available once both types.py and mapper.py are implemented.
Import individual submodules directly if only partial functionality is needed.
"""

from assistant.transports.ag_ui.types import (
    AGUIEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)

__all__ = [
    "AGUIEvent",
    "RunErrorEvent",
    "RunFinishedEvent",
    "RunStartedEvent",
    "TextMessageContentEvent",
    "TextMessageEndEvent",
    "TextMessageStartEvent",
    "ToolCallArgsEvent",
    "ToolCallEndEvent",
    "ToolCallStartEvent",
]

# map_harness_to_ag_ui is available after mapper.py is implemented.
# Import it lazily so this package can be loaded even when mapper is absent.
def __getattr__(name: str) -> object:  # noqa: ANN001
    if name == "map_harness_to_ag_ui":
        from assistant.transports.ag_ui.mapper import map_harness_to_ag_ui  # noqa: PLC0415

        return map_harness_to_ag_ui
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
