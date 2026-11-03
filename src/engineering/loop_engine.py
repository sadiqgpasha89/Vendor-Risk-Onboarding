"""Loop Engineering Module - Robust retry logic, error recovery, and feedback loops."""

import asyncio
import functools
import logging
from typing import Any, Callable, Dict, List, Optional, Type, TypeVar, Union
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field
import time
import random

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryStrategy(str, Enum):
    """Retry strategies for loop engineering."""

    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    CONSTANT_DELAY = "constant_delay"
    FIBONACCI_BACKOFF = "fibonacci_backoff"


class LoopCondition(str, Enum):
    """Loop termination conditions."""

    MAX_ITERATIONS = "max_iterations"
    CONVERGENCE = "convergence"
    TIMEOUT = "timeout"
    SUCCESS = "success"
    ERROR_THRESHOLD = "error_threshold"


@dataclass
class RetryConfig:
    """Configuration for retry logic."""

    max_retries: int = 3
    initial_delay: float = 1.0
    max_delay: float = 60.0
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    backoff_factor: float = 2.0
    jitter: bool = True
    retry_on: tuple = (Exception,)


@dataclass
class LoopConfig:
    """Configuration for feedback loops."""

    max_iterations: int = 10
    convergence_threshold: float = 0.95
    timeout_seconds: int = 300
    error_threshold: int = 3
    cooldown_seconds: float = 1.0


@dataclass
class LoopState:
    """State tracking for a loop execution."""

    iteration: int = 0
    errors: List[str] = field(default_factory=list)
    successes: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    convergence_score: float = 0.0
    total_attempts: int = 0

    def add_error(self, error: str) -> None:
        """Add an error to the loop state."""
        self.errors.append(f"[{datetime.utcnow().isoformat()}] {error}")

    def add_success(self, message: str) -> None:
        """Add a success message to the loop state."""
        self.successes.append(f"[{datetime.utcnow().isoformat()}] {message}")

    def is_converged(self, threshold: float) -> bool:
        """Check if loop has converged."""
        return self.convergence_score >= threshold

    def is_error_state(self) -> bool:
        """Check if loop has encountered errors."""
        return len(self.errors) > 0

    def get_duration(self) -> float:
        """Get loop execution duration in seconds."""
        end = self.end_time or datetime.utcnow()
        return (end - self.start_time).total_seconds()


class BackoffCalculator:
    """Calculate backoff delays based on strategy."""

    @staticmethod
    def calculate_delay(
        attempt: int,
        config: RetryConfig,
    ) -> float:
        """Calculate delay for given attempt."""
        if config.strategy == RetryStrategy.EXPONENTIAL_BACKOFF:
            delay = config.initial_delay * (config.backoff_factor ** attempt)
        elif config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = config.initial_delay * (attempt + 1)
        elif config.strategy == RetryStrategy.CONSTANT_DELAY:
            delay = config.initial_delay
        elif config.strategy == RetryStrategy.FIBONACCI_BACKOFF:
            delay = config.initial_delay * BackoffCalculator._fibonacci(attempt)
        else:
            delay = config.initial_delay

        # Cap at max_delay
        delay = min(delay, config.max_delay)

        # Add jitter if enabled
        if config.jitter:
            delay = delay * (0.5 + random.random())

        return delay

    @staticmethod
    def _fibonacci(n: int) -> int:
        """Get nth Fibonacci number."""
        if n <= 1:
            return 1
        a, b = 1, 1
        for _ in range(n - 1):
            a, b = b, a + b
        return b


def with_retry(config: Optional[RetryConfig] = None):
    """Decorator for retry logic."""

    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(config.max_retries):
                try:
                    return await func(*args, **kwargs)
                except config.retry_on as e:
                    last_exception = e
                    if attempt < config.max_retries - 1:
                        delay = BackoffCalculator.calculate_delay(attempt, config)
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}. "
                            f"Retrying in {delay:.2f}s. Error: {str(e)}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"All {config.max_retries} attempts failed for {func.__name__}"
                        )

            raise last_exception

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(config.max_retries):
                try:
                    return func(*args, **kwargs)
                except config.retry_on as e:
                    last_exception = e
                    if attempt < config.max_retries - 1:
                        delay = BackoffCalculator.calculate_delay(attempt, config)
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}. "
                            f"Retrying in {delay:.2f}s. Error: {str(e)}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {config.max_retries} attempts failed for {func.__name__}"
                        )

            raise last_exception

        # Return async or sync wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    return decorator


class FeedbackLoop:
    """Implements a feedback loop for iterative refinement."""

    def __init__(
        self,
        name: str,
        loop_func: Callable[[LoopState], Any],
        convergence_func: Optional[Callable[[Any], float]] = None,
        config: Optional[LoopConfig] = None,
    ):
        """Initialize feedback loop.

        Args:
            name: Name of the loop
            loop_func: Function to execute in each iteration
            convergence_func: Function to calculate convergence score (0-1)
            config: Loop configuration
        """
        self.name = name
        self.loop_func = loop_func
        self.convergence_func = convergence_func or (lambda x: 0.5)
        self.config = config or LoopConfig()
        self.state = LoopState()

    async def execute(self) -> LoopState:
        """Execute the feedback loop.

        Returns:
            LoopState with execution results
        """
        self.state = LoopState()
        start_time = datetime.utcnow()

        while True:
            # Check termination conditions
            if self.state.iteration >= self.config.max_iterations:
                logger.info(
                    f"Loop '{self.name}' terminated: Max iterations reached"
                )
                break

            self.state.iteration += 1
            self.state.total_attempts += 1

            elapsed = (datetime.utcnow() - start_time).total_seconds()
            if elapsed > self.config.timeout_seconds:
                logger.warning(
                    f"Loop '{self.name}' terminated: Timeout exceeded"
                )
                break

            if len(self.state.errors) > self.config.error_threshold:
                logger.error(
                    f"Loop '{self.name}' terminated: Error threshold exceeded"
                )
                break

            # Execute loop function
            try:
                result = await self.loop_func(self.state)
                self.state.add_success(f"Iteration {self.state.iteration} completed")

                # Calculate convergence
                convergence = self.convergence_func(result)
                self.state.convergence_score = convergence
                self.state.metrics[f"iteration_{self.state.iteration}"] = convergence

                # Check convergence
                if self.state.is_converged(self.config.convergence_threshold):
                    logger.info(
                        f"Loop '{self.name}' converged at iteration {self.state.iteration}"
                    )
                    break

            except Exception as e:
                self.state.add_error(f"Iteration {self.state.iteration}: {str(e)}")
                logger.error(f"Loop '{self.name}' error in iteration {self.state.iteration}: {e}")

            # Cooldown before next iteration
            await asyncio.sleep(self.config.cooldown_seconds)

        self.state.end_time = datetime.utcnow()
        logger.info(
            f"Loop '{self.name}' completed in {self.state.get_duration():.2f}s "
            f"with {self.state.iteration} iterations. "
            f"Convergence: {self.state.convergence_score:.2f}"
        )

        return self.state


class LoopChain:
    """Chain multiple feedback loops together."""

    def __init__(self, name: str):
        """Initialize loop chain."""
        self.name = name
        self.loops: List[FeedbackLoop] = []
        self.results: Dict[str, LoopState] = {}

    def add_loop(self, loop: FeedbackLoop) -> "LoopChain":
        """Add a loop to the chain."""
        self.loops.append(loop)
        return self

    async def execute(self) -> Dict[str, LoopState]:
        """Execute all loops in sequence."""
        logger.info(f"Starting loop chain '{self.name}' with {len(self.loops)} loops")

        for loop in self.loops:
            logger.info(f"Executing loop: {loop.name}")
            self.results[loop.name] = await loop.execute()

        return self.results

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of chain execution."""
        return {
            "chain_name": self.name,
            "total_loops": len(self.loops),
            "results": {
                name: {
                    "iterations": state.iteration,
                    "errors": len(state.errors),
                    "convergence": state.convergence_score,
                    "duration": state.get_duration(),
                }
                for name, state in self.results.items()
            },
        }
