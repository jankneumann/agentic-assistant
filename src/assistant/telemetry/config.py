"""TelemetryConfig — frozen dataclass with `_env()`-driven loader.

Loads ``LANGFUSE_*`` environment variables through the same ``_env()``
helper pattern used by ``assistant.core.persona`` so credentials stay
out of code and are picked up at discovery time. See spec
"Configuration Loading Through Persona Pattern" and design D13 for
the empty-string-credential semantics.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("assistant.telemetry")


def _env(var_name: str) -> str:
    """Read an env var; return empty string if unset.

    Mirrors ``assistant.core.persona._env`` so the telemetry layer
    follows the same credential-resolution convention.
    """
    if not var_name:
        return ""
    return os.environ.get(var_name, "")


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class TelemetryConfig:
    """Resolved telemetry configuration.

    All fields are typed defaults; ``from_env()`` is the canonical
    factory. The dataclass is frozen so the resolved config cannot be
    mutated mid-process.
    """

    enabled: bool
    public_key: str
    secret_key: str
    host: str
    environment: str
    flush_mode: str
    sample_rate: float

    @classmethod
    def from_env(cls) -> TelemetryConfig:
        """Build a TelemetryConfig from the process environment.

        Implements D13: empty-string credentials disable telemetry but
        emit a distinct warning so the user can tell the empty-but-
        present case from the fully-unset case.
        """
        enabled_raw = _env("LANGFUSE_ENABLED")
        public_key_raw = _env("LANGFUSE_PUBLIC_KEY")
        secret_key_raw = _env("LANGFUSE_SECRET_KEY")

        # Whitespace-only values normalize to empty per D13.
        public_key = public_key_raw.strip()
        secret_key = secret_key_raw.strip()

        host = _env("LANGFUSE_HOST").strip() or "https://cloud.langfuse.com"
        environment = (
            _env("LANGFUSE_ENVIRONMENT").strip()
            or os.environ.get("ASSISTANT_PROFILE", "").strip()
            or "local"
        )
        flush_mode = _env("LANGFUSE_FLUSH_MODE").strip() or "shutdown"

        sample_rate_raw = _env("LANGFUSE_SAMPLE_RATE").strip()
        try:
            sample_rate = float(sample_rate_raw) if sample_rate_raw else 1.0
        except ValueError:
            sample_rate = 1.0

        # Determine enabled state.
        wants_enabled = _truthy(enabled_raw)
        has_creds = bool(public_key) and bool(secret_key)

        # D13 — distinguish empty-but-present from fully-unset.
        # We check the *raw* values: if the env var is present (even as
        # empty/whitespace) and the user signaled enabled=true, that's
        # almost certainly a misconfiguration we want to flag.
        if wants_enabled:
            empty_but_present: list[str] = []
            if "LANGFUSE_PUBLIC_KEY" in os.environ and not public_key:
                empty_but_present.append("LANGFUSE_PUBLIC_KEY")
            if "LANGFUSE_SECRET_KEY" in os.environ and not secret_key:
                empty_but_present.append("LANGFUSE_SECRET_KEY")

            if empty_but_present:
                logger.warning(
                    "Telemetry disabled: LANGFUSE_ENABLED=true but the "
                    "following credentials are empty (set but blank or "
                    "whitespace-only): %s. Set non-empty values or unset "
                    "LANGFUSE_ENABLED to silence this warning.",
                    ", ".join(empty_but_present),
                )

        enabled = wants_enabled and has_creds

        return cls(
            enabled=enabled,
            public_key=public_key,
            secret_key=secret_key,
            host=host,
            environment=environment,
            flush_mode=flush_mode,
            sample_rate=sample_rate,
        )
