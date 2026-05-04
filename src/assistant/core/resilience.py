"""Runtime resilience primitives shared across http_tools, extensions,
and any future subsystem that needs retry + circuit-breaker behavior.

Per OpenSpec change ``error-resilience`` (P9). Design decisions D1-D15.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx
import tenacity

from assistant.telemetry.providers.base import ObservabilityProvider
from assistant.telemetry.sanitize import sanitize

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

logger = logging.getLogger("assistant.resilience")

_LAST_ERROR_MAX_CHARS = 200
_LAST_ERROR_TRUNCATION_SUFFIX = "..."


def _sanitize_and_truncate(error: BaseException | str) -> str:
    """Return a sanitized, truncated string representation of an error.

    Implements D12 (sanitize) and D14 (character-aware truncation).
    """
    raw = str(error) if isinstance(error, BaseException) else error
    cleaned = sanitize(raw)
    if len(cleaned) <= _LAST_ERROR_MAX_CHARS:
        return cleaned
    suffix_len = len(_LAST_ERROR_TRUNCATION_SUFFIX)
    return cleaned[: _LAST_ERROR_MAX_CHARS - suffix_len] + _LAST_ERROR_TRUNCATION_SUFFIX


@dataclass(frozen=True)
class RetryPolicy:
    """Immutable retry-policy configuration."""

    max_attempts: int
    base_delay_s: float
    max_delay_s: float
    jitter_factor: float
    retryable_status_codes: frozenset[int]
    retryable_exceptions: tuple[type[BaseException], ...]


DEFAULT_HTTP_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay_s=0.5,
    max_delay_s=8.0,
    jitter_factor=0.25,
    retryable_status_codes=frozenset({408, 425, 429, 500, 502, 503, 504}),
    retryable_exceptions=(
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
        httpx.ConnectError,
        httpx.RemoteProtocolError,
    ),
)


class HealthState(enum.Enum):
    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class HealthStatus:
    state: HealthState
    reason: str | None
    last_error: str | None
    checked_at: datetime
    breaker_key: str | None

    def __post_init__(self) -> None:
        # Enforce the spec invariant that any error string flowing into
        # HealthStatus.last_error is sanitized + truncated. This protects
        # against a future extension constructing HealthStatus directly
        # with raw upstream error text — see error-resilience capability
        # spec Requirement: "Error Strings Are Sanitized And Truncated".
        if self.last_error is not None:
            cleaned = _sanitize_and_truncate(self.last_error)
            if cleaned != self.last_error:
                # Frozen dataclass — must use object.__setattr__ to override
                # the field with the sanitized form.
                object.__setattr__(self, "last_error", cleaned)


def default_health_status_for_unimplemented(extension_name: str) -> HealthStatus:
    """Standard "stub" status used by every unwired extension stub."""
    # extension_name is accepted for symmetry with future per-extension
    # diagnostics (e.g., logging which stub was probed); the value
    # itself is intentionally not embedded in the status today.
    _ = extension_name
    return HealthStatus(
        state=HealthState.UNKNOWN,
        reason="extension is a stub",
        last_error=None,
        checked_at=datetime.now(UTC),
        breaker_key=None,
    )


class CircuitBreakerOpenError(Exception):
    """Raised when a guarded call is short-circuited by an open breaker."""

    def __init__(
        self,
        *,
        breaker_key: str,
        opened_at: datetime | None,
        next_probe_at: datetime | None,
        last_error_summary: str | None,
    ) -> None:
        self.breaker_key = breaker_key
        self.opened_at = opened_at
        self.next_probe_at = next_probe_at
        self.last_error_summary = (
            _sanitize_and_truncate(last_error_summary)
            if last_error_summary is not None
            else None
        )
        super().__init__(
            f"circuit breaker {breaker_key!r} is open "
            f"(opened_at={opened_at}, next_probe_at={next_probe_at})",
        )


@dataclass
class _BreakerState:
    state: str = "closed"  # one of {"closed", "open", "half_open"}
    consecutive_failures: int = 0
    opened_at: datetime | None = None
    next_probe_at: datetime | None = None
    last_error: str | None = None
    in_flight_probe: bool = False


class CircuitBreaker:
    """Per-backend circuit breaker (D3, D5, D13)."""

    def __init__(
        self,
        *,
        key: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._key = key
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._lock = asyncio.Lock()
        self._st = _BreakerState()

    @property
    def key(self) -> str:
        return self._key

    @property
    def state(self) -> str:
        return self._st.state

    @property
    def consecutive_failures(self) -> int:
        return self._st.consecutive_failures

    @property
    def last_error(self) -> str | None:
        return self._st.last_error

    @property
    def opened_at(self) -> datetime | None:
        return self._st.opened_at

    @property
    def next_probe_at(self) -> datetime | None:
        return self._st.next_probe_at

    async def record_failure(self, error: BaseException | str) -> None:
        """Mark an availability failure. Caller MUST classify before calling.

        Non-availability failures (e.g., HTTP 401) MUST NOT be reported here.
        """
        async with self._lock:
            self._st.consecutive_failures += 1
            self._st.last_error = _sanitize_and_truncate(error)
            if self._st.state == "half_open":
                # Failed probe — re-open with fresh cooldown.
                self._open_locked()
            elif (
                self._st.state == "closed"
                and self._st.consecutive_failures >= self._failure_threshold
            ):
                self._open_locked()
            self._st.in_flight_probe = False

    async def record_success(self) -> None:
        async with self._lock:
            prev_state = self._st.state
            self._st.consecutive_failures = 0
            self._st.state = "closed"
            self._st.opened_at = None
            self._st.next_probe_at = None
            self._st.in_flight_probe = False
            if prev_state == "half_open":
                _emit_transition_span(
                    from_state="half_open",
                    to_state="closed",
                    breaker_key=self._key,
                    last_error_summary=None,
                )

    @asynccontextmanager
    async def acquire_admission(self) -> AsyncIterator[None]:
        """Either admit the caller, or raise CircuitBreakerOpenError.

        If the breaker is closed: admit.
        If the breaker is open and cooldown has elapsed: admit exactly one
        caller as the half-open probe; concurrent callers are rejected.
        Otherwise: reject.
        """
        admitted_as_probe = False
        async with self._lock:
            now = datetime.now(UTC)
            if self._st.state == "open":
                if (
                    self._st.next_probe_at is not None
                    and now >= self._st.next_probe_at
                    and not self._st.in_flight_probe
                ):
                    self._st.state = "half_open"
                    self._st.in_flight_probe = True
                    admitted_as_probe = True
                    _emit_transition_span(
                        from_state="open",
                        to_state="half_open",
                        breaker_key=self._key,
                        last_error_summary=self._st.last_error,
                    )
                else:
                    raise CircuitBreakerOpenError(
                        breaker_key=self._key,
                        opened_at=self._st.opened_at,
                        next_probe_at=self._st.next_probe_at,
                        last_error_summary=self._st.last_error,
                    )
            elif self._st.state == "half_open":
                # Probe is already in flight from another caller.
                raise CircuitBreakerOpenError(
                    breaker_key=self._key,
                    opened_at=self._st.opened_at,
                    next_probe_at=self._st.next_probe_at,
                    last_error_summary=self._st.last_error,
                )
            # state == "closed" → fall through and admit.
        try:
            yield
        finally:
            if admitted_as_probe:
                async with self._lock:
                    # If neither record_success nor record_failure was called
                    # (e.g. cancellation), clear the probe flag here so the
                    # breaker is not permanently held.
                    self._st.in_flight_probe = False

    def _open_locked(self) -> None:
        """Move the breaker to open. Caller MUST hold ``self._lock``."""
        prev_state = self._st.state
        now = datetime.now(UTC)
        self._st.state = "open"
        self._st.opened_at = now
        self._st.next_probe_at = datetime.fromtimestamp(
            now.timestamp() + self._cooldown_seconds,
            tz=UTC,
        )
        _emit_transition_span(
            from_state=prev_state,
            to_state="open",
            breaker_key=self._key,
            last_error_summary=self._st.last_error,
        )


class CircuitBreakerRegistry:
    """Process-wide singleton registry of breakers keyed by canonical string."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}
        self._lock = asyncio.Lock()

    def get_breaker(self, key: str) -> CircuitBreaker:
        """Return existing breaker for ``key`` or create one with defaults.

        Lookup is fast-path lock-free; insertion uses a coarse asyncio.Lock
        only when a breaker for the key has not been created yet. Because
        we are inside a single event loop, ``dict.setdefault`` is itself
        atomic with respect to other coroutines — but we use the lock to
        ensure exactly-one ``CircuitBreaker.__init__`` call per key.
        """
        existing = self._breakers.get(key)
        if existing is not None:
            return existing
        # Slow path: synchronously create. ``__init__`` is non-async and
        # the registry is in-process, so we don't need to await the lock.
        return self._breakers.setdefault(key, CircuitBreaker(key=key))


_REGISTRY: CircuitBreakerRegistry | None = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = CircuitBreakerRegistry()
    return _REGISTRY


def health_status_from_breaker(
    breaker: CircuitBreaker,
    *,
    key: str,
) -> HealthStatus:
    """Map breaker state → HealthStatus per D3/D8."""
    state_map = {
        "closed": HealthState.OK,
        "half_open": HealthState.DEGRADED,
        "open": HealthState.UNAVAILABLE,
    }
    return HealthStatus(
        state=state_map.get(breaker.state, HealthState.UNKNOWN),
        reason=None,
        last_error=breaker.last_error,
        checked_at=datetime.now(UTC),
        breaker_key=key,
    )


# ---------------------------------------------------------------------------
# Observability helpers — emit start_span events without introducing a new
# Protocol method. Provider lookup is lazy + best-effort; if the telemetry
# subsystem is in a degraded state, resilience operations continue silently.
# ---------------------------------------------------------------------------


def _get_provider() -> ObservabilityProvider | None:
    try:
        from assistant.telemetry.factory import get_observability_provider
    except Exception:
        return None
    try:
        return get_observability_provider()
    except Exception:
        return None


def _emit_attempt_span(
    *,
    breaker_key: str,
    attempt_number: int,
    delay_before_attempt_s: float,
    error_type: str | None,
) -> None:
    provider = _get_provider()
    if provider is None:
        return
    attrs: dict[str, Any] = {
        "breaker_key": breaker_key,
        "attempt_number": attempt_number,
        "delay_before_attempt_s": delay_before_attempt_s,
    }
    if error_type is not None:
        attrs["error_type"] = error_type
    try:
        with provider.start_span("resilience.http_attempt", attrs):
            pass
    except Exception:
        logger.debug("attempt span emission failed", exc_info=True)


def _emit_transition_span(
    *,
    from_state: str,
    to_state: str,
    breaker_key: str,
    last_error_summary: str | None,
) -> None:
    provider = _get_provider()
    if provider is None:
        return
    attrs: dict[str, Any] = {
        "breaker_key": breaker_key,
        "from_state": from_state,
        "to_state": to_state,
    }
    if last_error_summary is not None:
        attrs["last_error_summary"] = last_error_summary
    try:
        with provider.start_span("resilience.breaker_transition", attrs):
            pass
    except Exception:
        logger.debug("breaker transition span emission failed", exc_info=True)


def _emit_short_circuit_span(error: CircuitBreakerOpenError) -> None:
    provider = _get_provider()
    if provider is None:
        return
    attrs: dict[str, Any] = {
        "breaker_key": error.breaker_key,
        "opened_at": str(error.opened_at) if error.opened_at else None,
        "next_probe_at": (
            str(error.next_probe_at) if error.next_probe_at else None
        ),
    }
    try:
        with provider.start_span("resilience.short_circuit", attrs):
            pass
    except Exception:
        logger.debug("short_circuit span emission failed", exc_info=True)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def _is_retryable(
    error: BaseException,
    policy: RetryPolicy,
) -> bool:
    """Classify an error as retryable by the tenacity retry predicate.

    NOTE: distinct from ``_is_availability_failure``. ``CircuitBreakerOpenError``
    is an availability failure for accounting purposes but is NOT retryable —
    retrying would just keep hitting the same open breaker until cooldown
    elapses, which adds latency and duplicate short-circuit telemetry without
    a chance of recovery.
    """
    if isinstance(error, policy.retryable_exceptions):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in policy.retryable_status_codes
    return False


def _is_availability_failure(
    error: BaseException,
    policy: RetryPolicy,
) -> bool:
    """Classify an error as an availability failure for breaker accounting (D5).

    A superset of ``_is_retryable``: includes ``CircuitBreakerOpenError`` so
    nested guarded calls that hit an inner open breaker are still recorded
    as upstream-availability failures on the outer breaker.
    """
    if _is_retryable(error, policy):
        return True
    if isinstance(error, CircuitBreakerOpenError):
        return True
    return False


def _backoff_delay(attempt: int, policy: RetryPolicy) -> float:
    """Exponential backoff with jitter for ``attempt`` (1-indexed)."""
    base = min(policy.max_delay_s, policy.base_delay_s * (2 ** (attempt - 1)))
    jitter = random.uniform(
        1.0 - policy.jitter_factor,
        1.0 + policy.jitter_factor,
    )
    return base * jitter


def resilient_http(
    *,
    breaker_key: str,
    policy: RetryPolicy | None = None,
) -> Callable[
    [Callable[..., Awaitable[Any]]],
    Callable[..., Awaitable[Any]],
]:
    """Decorator factory wrapping an ``async def`` with retry + breaker.

    See ``error-resilience`` capability spec for the full contract.
    """
    active_policy = policy or DEFAULT_HTTP_RETRY_POLICY

    def _decorator(
        fn: Callable[..., Awaitable[Any]],
    ) -> Callable[..., Awaitable[Any]]:
        async def _wrapped(*args: Any, **kwargs: Any) -> Any:
            registry = get_circuit_breaker_registry()
            breaker = registry.get_breaker(breaker_key)

            try:
                ctx = breaker.acquire_admission()
            except CircuitBreakerOpenError as exc:
                # acquire_admission is a context manager factory; this
                # branch is unreachable in practice but keeps mypy happy.
                _emit_short_circuit_span(exc)
                raise

            try:
                async with ctx:
                    return await _run_with_retry(
                        fn=fn,
                        args=args,
                        kwargs=kwargs,
                        breaker=breaker,
                        policy=active_policy,
                    )
            except CircuitBreakerOpenError as exc:
                _emit_short_circuit_span(exc)
                raise

        _wrapped.__wrapped__ = fn  # type: ignore[attr-defined]
        return _wrapped

    return _decorator


async def _run_with_retry(
    *,
    fn: Callable[..., Awaitable[Any]],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    breaker: CircuitBreaker,
    policy: RetryPolicy,
) -> Any:
    """Drive the retry loop while emitting per-attempt observability spans."""

    def _retry_predicate(retry_state: tenacity.RetryCallState) -> bool:
        outcome = retry_state.outcome
        if outcome is None or not outcome.failed:
            return False
        exc = outcome.exception()
        # Use _is_retryable, NOT _is_availability_failure — see the
        # function docstrings for why CircuitBreakerOpenError must not
        # be retried (it is an availability failure but retrying it has
        # no chance of recovery before cooldown elapses).
        return exc is not None and _is_retryable(exc, policy)

    delay_holder: dict[str, float] = {"delay": 0.0}

    def _wait_strategy(retry_state: tenacity.RetryCallState) -> float:
        delay = _backoff_delay(retry_state.attempt_number, policy)
        delay_holder["delay"] = delay
        return delay

    try:
        async for attempt in tenacity.AsyncRetrying(
            stop=tenacity.stop_after_attempt(policy.max_attempts),
            wait=_wait_strategy,
            retry=_retry_predicate,
            reraise=True,
        ):
            with attempt:
                attempt_number = attempt.retry_state.attempt_number
                this_attempt_error: str | None = None
                try:
                    result = await fn(*args, **kwargs)
                except Exception as exc:
                    # Note: NOT BaseException — KeyboardInterrupt /
                    # SystemExit / asyncio.CancelledError must propagate
                    # without being recorded as breaker failures.
                    this_attempt_error = type(exc).__name__
                    # Emit the per-attempt span BEFORE re-raising so the
                    # span carries this attempt's outcome (error_type)
                    # instead of being attributed to the next attempt's
                    # entry — see observability spec scenario
                    # "Successful retry emits one trace_tool_call plus
                    # per-attempt spans".
                    _emit_attempt_span(
                        breaker_key=breaker.key,
                        attempt_number=attempt_number,
                        delay_before_attempt_s=(
                            delay_holder["delay"] if attempt_number > 1 else 0.0
                        ),
                        error_type=this_attempt_error,
                    )
                    raise
                # Successful attempt — emit span with error_type=None.
                _emit_attempt_span(
                    breaker_key=breaker.key,
                    attempt_number=attempt_number,
                    delay_before_attempt_s=(
                        delay_holder["delay"] if attempt_number > 1 else 0.0
                    ),
                    error_type=None,
                )
        await breaker.record_success()
        return result
    except Exception as exc:
        if _is_availability_failure(exc, policy):
            await breaker.record_failure(exc)
        # Non-availability failures are re-raised without affecting breaker
        # state — see D5.
        raise
