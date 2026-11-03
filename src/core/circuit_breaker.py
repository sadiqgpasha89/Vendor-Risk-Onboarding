"""Enterprise Circuit Breaker with graceful degradation and fallback metrics."""

import time
import asyncio
import logging
from enum import Enum
from typing import Callable, Any, Optional, Dict
from dataclasses import dataclass, field
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "CLOSED"      # Normal operation
    OPEN = "OPEN"          # Failing, fast-reject requests
    HALF_OPEN = "HALF_OPEN"  # Testing if dependency has recovered


class CircuitBreakerOpenException(Exception):
    """Raised when a call is attempted through an open circuit breaker."""

    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker '{name}' is OPEN. Retry after {retry_after:.1f}s")


@dataclass
class CircuitBreakerStats:
    name: str
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    consecutive_failures: int = 0
    last_failure_time: Optional[float] = None
    state: CircuitState = CircuitState.CLOSED
    opened_count: int = 0


class CircuitBreaker:
    """Production circuit breaker supporting async & sync invocation and fallback degradation."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_success_threshold: int = 2,
        fallback_factory: Optional[Callable[..., Any]] = None,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_success_threshold = half_open_success_threshold
        self.fallback_factory = fallback_factory

        self.stats = CircuitBreakerStats(name=name)
        self._half_open_successes = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self.stats.state == CircuitState.OPEN:
            if self.stats.last_failure_time and (time.time() - self.stats.last_failure_time) >= self.recovery_timeout:
                self.stats.state = CircuitState.HALF_OPEN
                self._half_open_successes = 0
                logger.info(f"Circuit breaker '{self.name}' entered HALF_OPEN state.")
        return self.stats.state

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute async function protected by the circuit breaker."""
        current_state = self.state

        if current_state == CircuitState.OPEN:
            retry_after = max(0.0, self.recovery_timeout - (time.time() - (self.stats.last_failure_time or 0)))
            logger.warning(f"Circuit '{self.name}' OPEN. Short-circuiting call.")
            if self.fallback_factory:
                return self.fallback_factory(*args, **kwargs)
            raise CircuitBreakerOpenException(self.name, retry_after)

        self.stats.total_calls += 1
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            await self._record_success()
            return result
        except Exception as exc:
            await self._record_failure(exc)
            if self.fallback_factory:
                logger.warning(f"Circuit '{self.name}' failed. Executing fallback.")
                return self.fallback_factory(*args, **kwargs)
            raise

    async def _record_success(self):
        async with self._lock:
            self.stats.successful_calls += 1
            if self.stats.state == CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.half_open_success_threshold:
                    self.stats.state = CircuitState.CLOSED
                    self.stats.consecutive_failures = 0
                    logger.info(f"Circuit breaker '{self.name}' RECOVERED and is now CLOSED.")
            elif self.stats.state == CircuitState.CLOSED:
                self.stats.consecutive_failures = 0

    async def _record_failure(self, error: Exception):
        async with self._lock:
            self.stats.failed_calls += 1
            self.stats.consecutive_failures += 1
            self.stats.last_failure_time = time.time()
            logger.error(f"Circuit '{self.name}' failure #{self.stats.consecutive_failures}: {error}")

            if self.stats.consecutive_failures >= self.failure_threshold:
                self.stats.state = CircuitState.OPEN
                self.stats.opened_count += 1
                logger.error(f"Circuit breaker '{self.name}' TRIPPED to OPEN state! Will retry in {self.recovery_timeout}s.")

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.stats.name,
            "state": self.state.value,
            "consecutive_failures": self.stats.consecutive_failures,
            "total_calls": self.stats.total_calls,
            "failed_calls": self.stats.failed_calls,
            "successful_calls": self.stats.successful_calls,
            "opened_count": self.stats.opened_count,
        }


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 30.0,
    fallback_factory: Optional[Callable] = None,
):
    """Decorator to protect async and sync functions with a circuit breaker."""
    cb = CircuitBreaker(
        name=name,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        fallback_factory=fallback_factory,
    )

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await cb.call(func, *args, **kwargs)

        wrapper.circuit_breaker = cb
        return wrapper

    return decorator
