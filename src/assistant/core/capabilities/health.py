"""Endpoint health monitoring for local model registry entries — P20.

Local OpenAI-compatible endpoints (GX10 via NIM / vLLM / Ollama — or
any host) come and go; the model registry should not blindly dispatch
to a node that is known to be down. Registry entries may declare an
optional ``health:`` block (``path`` / ``timeout`` / ``ttl``); the
:class:`EndpointHealthMonitor` probes ``GET <endpoint><path>``
asynchronously and caches the verdict, and
``RegistryModelProvider.resolve`` consults the *cached* state only —
the synchronous resolve path never blocks on a probe.

Health state is three-valued (local-inference-node design D1):

- **HEALTHY** — no ``health:`` declared (exempt), or a fresh positive
  verdict: eligible.
- **UNKNOWN** — declared but never probed, or the verdict aged past
  ``ttl``: eligible (optimistic — the P19 bind-time fallback walk
  still covers a dead endpoint; health filtering only prunes
  *known*-dead entries).
- **UNHEALTHY** — a fresh negative verdict: skipped during
  resolution.

Pre-warm points (design D3): ``assistant models check-health``,
daemon startup, and programmatic :meth:`EndpointHealthMonitor.refresh`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:  # pragma: no cover — typing only, avoids the cycle
    from assistant.core.capabilities.models import ModelRef

logger = logging.getLogger(__name__)

#: Probe path appended to the entry endpoint. ``GET <endpoint>/models``
#: is the natural OpenAI-compatible liveness probe — vLLM, Ollama's
#: OpenAI facade, and NIM all serve it.
DEFAULT_HEALTH_PATH = "/models"

#: Probe timeout in seconds.
DEFAULT_HEALTH_TIMEOUT = 2.0

#: Freshness window of a cached probe verdict, in seconds. Older
#: verdicts decay to UNKNOWN (eligible) rather than sticking.
DEFAULT_HEALTH_TTL = 60.0

_HEALTH_KEYS = frozenset({"path", "timeout", "ttl"})


@dataclass(frozen=True)
class EndpointHealth:
    """Parsed ``health:`` block of one registry entry."""

    path: str = DEFAULT_HEALTH_PATH
    timeout: float = DEFAULT_HEALTH_TIMEOUT
    ttl: float = DEFAULT_HEALTH_TTL


class HealthStatus(Enum):
    """Cached health verdict consumed by resolution (design D1)."""

    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


def parse_endpoint_health(raw: Any) -> EndpointHealth:
    """Parse and validate a registry entry's ``health:`` block.

    Raises :class:`ValueError` with an actionable message on unknown
    keys, a ``path`` not starting with ``/``, or non-positive
    ``timeout`` / ``ttl`` values. Callers (``parse_model_registry``)
    wrap the error with the entry name.
    """
    if not isinstance(raw, dict):
        raise ValueError(
            f"health: expected a mapping with optional keys "
            f"{sorted(_HEALTH_KEYS)}, got {type(raw).__name__}."
        )
    unknown = sorted(set(raw) - _HEALTH_KEYS)
    if unknown:
        raise ValueError(
            f"health: unknown keys {unknown}. Allowed keys: "
            f"{sorted(_HEALTH_KEYS)}."
        )
    path = raw.get("path", DEFAULT_HEALTH_PATH)
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError(
            f"health.path: expected a string starting with '/', got "
            f"{path!r}."
        )
    try:
        timeout = float(raw.get("timeout", DEFAULT_HEALTH_TIMEOUT))
        ttl = float(raw.get("ttl", DEFAULT_HEALTH_TTL))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"health: timeout and ttl must be numbers — {exc}"
        ) from exc
    if timeout <= 0:
        raise ValueError(f"health.timeout: must be positive, got {timeout}.")
    if ttl <= 0:
        raise ValueError(f"health.ttl: must be positive, got {ttl}.")
    return EndpointHealth(path=path, timeout=timeout, ttl=ttl)


def probe_url(ref: ModelRef) -> str:
    """The probe URL for a health-declaring ref."""
    health = ref.health
    assert health is not None
    return ref.endpoint.rstrip("/") + health.path


class EndpointHealthMonitor:
    """TTL-cached endpoint health state, shared across providers.

    Verdicts are keyed by registry entry name and stamped with the
    injectable ``clock`` (default ``time.monotonic``) for TTL
    evaluation. Probes are async and explicit — nothing on the
    synchronous resolve path ever calls :meth:`probe`.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._state: dict[str, tuple[bool, float]] = {}

    def status(self, ref: ModelRef) -> HealthStatus:
        """Cached verdict for ``ref`` — never issues a network call."""
        if ref.health is None:
            return HealthStatus.HEALTHY
        record = self._state.get(ref.name)
        if record is None:
            return HealthStatus.UNKNOWN
        healthy, checked_at = record
        if self._clock() - checked_at > ref.health.ttl:
            return HealthStatus.UNKNOWN
        return HealthStatus.HEALTHY if healthy else HealthStatus.UNHEALTHY

    def record(self, name: str, healthy: bool) -> None:
        """Stamp a verdict for entry ``name`` at the current clock."""
        self._state[name] = (healthy, self._clock())

    def clear(self) -> None:
        self._state.clear()

    async def probe(
        self, ref: ModelRef, *, http_client: httpx.AsyncClient | None = None
    ) -> bool:
        """Probe one health-declaring ref and cache the verdict.

        ``GET <endpoint><path>`` with the configured timeout, TLS
        verification on, redirects refused (a redirect is an unhealthy
        verdict — mirroring the http_tools D9 posture). 2xx == healthy;
        every other outcome, including transport errors, is unhealthy.
        Tests inject ``http_client`` (``httpx.MockTransport``-backed)
        so nothing touches the network.
        """
        health = ref.health
        if health is None or not ref.endpoint:
            return False
        url = probe_url(ref)
        healthy = False
        try:
            if http_client is not None:
                response = await http_client.get(
                    url, timeout=health.timeout, follow_redirects=False
                )
            else:
                async with httpx.AsyncClient(
                    timeout=health.timeout, follow_redirects=False, verify=True
                ) as client:
                    response = await client.get(url)
            healthy = 200 <= response.status_code < 300
        except httpx.HTTPError as exc:
            logger.debug(
                "health probe for %r (%s) failed: %s", ref.name, url, exc
            )
            healthy = False
        self.record(ref.name, healthy)
        if not healthy:
            logger.warning(
                "model endpoint %r is unhealthy (probe %s)", ref.name, url
            )
        return healthy

    async def refresh(
        self,
        refs: Iterable[ModelRef],
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> dict[str, bool]:
        """Probe every health-declaring ref concurrently.

        Refs without a ``health:`` block (or without an endpoint) are
        skipped — a persona with no health-checked entries refreshes
        with zero network calls.
        """
        targets = [r for r in refs if r.health is not None and r.endpoint]
        if not targets:
            return {}
        verdicts = await asyncio.gather(
            *(self.probe(r, http_client=http_client) for r in targets)
        )
        return {ref.name: ok for ref, ok in zip(targets, verdicts, strict=True)}


#: Process-shared monitor (mirrors the graphiti/engine cache pattern)
#: so a CLI probe or daemon pre-warm benefits every subsequent
#: resolution in the same process.
_default_monitor = EndpointHealthMonitor()


def default_health_monitor() -> EndpointHealthMonitor:
    return _default_monitor


def _reset_default_health_monitor() -> None:
    """Test hook — clear the shared monitor's cached verdicts."""
    _default_monitor.clear()
