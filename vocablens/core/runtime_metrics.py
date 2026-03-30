from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol


class RuntimeMetricsSink(Protocol):
    def observe_lock_wait_ms(self, *, component: str, value_ms: float) -> None: ...
    def observe_queue_depth(self, *, component: str, value: int) -> None: ...
    def observe_queue_lag_ms(self, *, component: str, value_ms: float) -> None: ...
    def increment_outbox_retry(self, *, component: str, count: int) -> None: ...
    def observe_worker_throughput(self, *, component: str, count: int) -> None: ...


class NoOpRuntimeMetricsSink:
    def observe_lock_wait_ms(self, *, component: str, value_ms: float) -> None:
        return None

    def observe_queue_depth(self, *, component: str, value: int) -> None:
        return None

    def observe_queue_lag_ms(self, *, component: str, value_ms: float) -> None:
        return None

    def increment_outbox_retry(self, *, component: str, count: int) -> None:
        return None

    def observe_worker_throughput(self, *, component: str, count: int) -> None:
        return None


@dataclass
class InMemoryRuntimeMetricsSink:
    lock_wait_ms: dict[str, list[float]] = field(default_factory=dict)
    queue_depth: dict[str, list[int]] = field(default_factory=dict)
    queue_lag_ms: dict[str, list[float]] = field(default_factory=dict)
    outbox_retries: dict[str, int] = field(default_factory=dict)
    throughput: dict[str, int] = field(default_factory=dict)

    def observe_lock_wait_ms(self, *, component: str, value_ms: float) -> None:
        self.lock_wait_ms.setdefault(component, []).append(float(value_ms))

    def observe_queue_depth(self, *, component: str, value: int) -> None:
        self.queue_depth.setdefault(component, []).append(int(value))

    def observe_queue_lag_ms(self, *, component: str, value_ms: float) -> None:
        self.queue_lag_ms.setdefault(component, []).append(float(value_ms))

    def increment_outbox_retry(self, *, component: str, count: int) -> None:
        self.outbox_retries[component] = int(self.outbox_retries.get(component, 0)) + int(count)

    def observe_worker_throughput(self, *, component: str, count: int) -> None:
        self.throughput[component] = int(self.throughput.get(component, 0)) + int(count)


_METRICS_LOCK = Lock()
_METRICS_SINK: RuntimeMetricsSink = NoOpRuntimeMetricsSink()


def set_runtime_metrics_sink(sink: RuntimeMetricsSink) -> None:
    global _METRICS_SINK
    with _METRICS_LOCK:
        _METRICS_SINK = sink


def runtime_metrics() -> RuntimeMetricsSink:
    with _METRICS_LOCK:
        return _METRICS_SINK
