"""Factory + 3-level graceful degradation for the telemetry layer.

Design D1 (singleton lifecycle), D2 (3-level state machine), D6
(atexit-registered shutdown). The factory caches the resolved
provider in a module-level variable so the Langfuse SDK client is
reused across calls (essential for batching).

Three levels:

1. **Disabled** — ``TelemetryConfig.enabled`` is ``False`` (or
   credentials are empty per D13). Returns NoopProvider; no warning,
   no langfuse import attempted.
2. **Import failure** — ``import langfuse`` raises. Returns
   NoopProvider; emits one-shot warning on logger
   ``assistant.telemetry``.
3. **Runtime failure** — ``LangfuseProvider.setup()`` raises (e.g.
   the SDK constructor blows up). Returns NoopProvider; emits one-
   shot warning. Original exception is NOT re-raised.

The "one warning per process" guarantee is implemented via a module-
level set ``_warned_levels``. The autouse test fixture in
``tests/telemetry/conftest.py`` clears both ``_provider`` and
``_warned_levels`` before each test so degradation paths can be
asserted independently.
"""

from __future__ import annotations

import atexit
import logging
import threading
from typing import TYPE_CHECKING

from assistant.telemetry.config import TelemetryConfig
from assistant.telemetry.providers.noop import NoopProvider

if TYPE_CHECKING:
    from assistant.telemetry.providers.base import ObservabilityProvider

logger = logging.getLogger("assistant.telemetry")

# Module-level singleton state — D1.
_provider: ObservabilityProvider | None = None
_provider_lock = threading.Lock()

# One-shot warning tracker — D2. Each membership marker is the level
# string ("import_error", "init_error", "empty_creds_with_enabled"). The
# "empty_creds_with_enabled" key is emitted from this module (not from
# config.py) per iter-2 fix H so the dedup architecture stays
# consistent — every degradation-shaped warning routes through
# ``_warn_once`` regardless of where the underlying observation was
# captured.
_warned_levels: set[str] = set()


def _warn_once(level: str, message: str) -> None:
    """Emit ``message`` on logger ``assistant.telemetry`` exactly once.

    Subsequent calls with the same ``level`` are dropped silently —
    this enforces the spec's "MUST NOT repeat on subsequent
    get_observability_provider() calls".
    """
    if level in _warned_levels:
        return
    _warned_levels.add(level)
    logger.warning(message)


def _init_provider() -> ObservabilityProvider:
    """Resolve a provider per the 3-level state machine.

    Always returns a functional provider — never raises.
    """
    config = TelemetryConfig.from_env()

    # Iter-2 fix H — distinguish the empty-but-present credential case
    # from the fully-unset case. ``config.empty_creds_present`` is set
    # by ``TelemetryConfig.from_env()`` when LANGFUSE_ENABLED=true but
    # one or both creds are blank. Emitting via ``_warn_once`` here
    # (not from inside ``from_env``) keeps the dedup centralised.
    if config.empty_creds_present:
        _warn_once(
            "empty_creds_with_enabled",
            "Telemetry disabled: LANGFUSE_ENABLED=true but the following "
            "credentials are empty (set but blank or whitespace-only): "
            f"{', '.join(config.empty_creds_present)}. Set non-empty "
            "values or unset LANGFUSE_ENABLED to silence this warning.",
        )

    # Level 1: disabled.
    if not config.enabled:
        return NoopProvider()

    # Level 2: import failure.
    try:
        from assistant.telemetry.providers.langfuse import LangfuseProvider
    except ImportError as exc:
        _warn_once(
            "import_error",
            f"Telemetry: failed to import langfuse provider module: {exc}; "
            f"falling back to noop. Install the optional `[telemetry]` extra "
            f"to enable Langfuse.",
        )
        return NoopProvider()

    provider = LangfuseProvider(config)

    # Level 2 continued: setup may raise ImportError if `langfuse`
    # itself is not installed (the LangfuseProvider module imports
    # cleanly because it only does `from langfuse import Langfuse`
    # inside setup()).
    try:
        provider.setup()
    except ImportError as exc:
        _warn_once(
            "import_error",
            f"Telemetry: import of the langfuse SDK failed ({exc}); "
            f"falling back to noop. Run `uv sync --extra telemetry` to install.",
        )
        return NoopProvider()
    except Exception as exc:
        # Level 3: runtime init failure (constructor exception, etc.).
        _warn_once(
            "init_error",
            f"Telemetry: LangfuseProvider.setup() raised {type(exc).__name__}: "
            f"{exc}; falling back to noop. Telemetry is disabled for this "
            f"process.",
        )
        return NoopProvider()

    return provider


def get_observability_provider() -> ObservabilityProvider:
    """Return the process-wide telemetry provider (singleton).

    First call resolves a provider via the 3-level state machine and
    registers an atexit handler to drain its buffer on process exit.
    Subsequent calls return the cached instance.
    """
    global _provider
    if _provider is not None:
        return _provider
    with _provider_lock:
        if _provider is not None:
            return _provider
        provider = _init_provider()
        atexit.register(provider.shutdown)
        _provider = provider
        return provider
