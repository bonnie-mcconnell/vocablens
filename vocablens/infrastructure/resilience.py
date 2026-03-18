import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

from vocablens.infrastructure.observability.metrics import CIRCUIT_BREAKER_EVENTS, EXTERNAL_CALLS

T = TypeVar("T")


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 3
    reset_timeout_seconds: float = 30.0

    def __post_init__(self):
        self._failure_count = 0
        self._open_until = 0.0

    def ensure_closed(self) -> None:
        now = time.monotonic()
        if now < self._open_until:
            CIRCUIT_BREAKER_EVENTS.labels(name=self.name, event="blocked").inc()
            raise RuntimeError(f"{self.name} circuit open")

    def record_success(self) -> None:
        self._failure_count = 0
        self._open_until = 0.0
        CIRCUIT_BREAKER_EVENTS.labels(name=self.name, event="success").inc()

    def record_failure(self) -> None:
        self._failure_count += 1
        CIRCUIT_BREAKER_EVENTS.labels(name=self.name, event="failure").inc()
        if self._failure_count >= self.failure_threshold:
            self._open_until = time.monotonic() + self.reset_timeout_seconds
            CIRCUIT_BREAKER_EVENTS.labels(name=self.name, event="opened").inc()


async def async_retry(
    name: str,
    func: Callable[[], Awaitable[T]],
    attempts: int,
    backoff_base: float,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            value = await func()
            EXTERNAL_CALLS.labels(name=name, result="success").inc()
            return value
        except Exception as exc:  # pragma: no cover - network dependent
            last_exc = exc
            EXTERNAL_CALLS.labels(name=name, result="failure").inc()
            if attempt == attempts - 1:
                raise
            delay = backoff_base * (2**attempt) + random.uniform(0, backoff_base / 4)
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{name} retry loop exited unexpectedly")


def sync_retry(
    name: str,
    func: Callable[[], T],
    attempts: int,
    backoff_base: float,
) -> T:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            value = func()
            EXTERNAL_CALLS.labels(name=name, result="success").inc()
            return value
        except Exception as exc:  # pragma: no cover - network dependent
            last_exc = exc
            EXTERNAL_CALLS.labels(name=name, result="failure").inc()
            if attempt == attempts - 1:
                raise
            delay = backoff_base * (2**attempt) + random.uniform(0, backoff_base / 4)
            time.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{name} retry loop exited unexpectedly")
