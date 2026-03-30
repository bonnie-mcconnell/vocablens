from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol


class RuntimeMetricsSink(Protocol):
    def observe_lock_wait_ms(self, *, component: str, value_ms: float) -> None: ...
    def observe_queue_depth(self, *, component: str, value: int) -> None: ...
    def observe_queue_lag_ms(self, *, component: str, value_ms: float) -> None: ...
    def increment_outbox_retry(self, *, component: str, count: int) -> None: ...
    def increment_dlq(self, *, component: str, count: int) -> None: ...
    def observe_worker_throughput(self, *, component: str, count: int) -> None: ...
    def lock_wait_p95(self, component: str) -> float: ...
    def queue_lag_p95(self, component: str) -> float: ...


class NoOpRuntimeMetricsSink:
    def observe_lock_wait_ms(self, *, component: str, value_ms: float) -> None:
        return None

    def observe_queue_depth(self, *, component: str, value: int) -> None:
        return None

    def observe_queue_lag_ms(self, *, component: str, value_ms: float) -> None:
        return None

    def increment_outbox_retry(self, *, component: str, count: int) -> None:
        return None

    def increment_dlq(self, *, component: str, count: int) -> None:
        return None

    def observe_worker_throughput(self, *, component: str, count: int) -> None:
        return None

    def lock_wait_p95(self, component: str) -> float:
        _ = component
        return 0.0

    def queue_lag_p95(self, component: str) -> float:
        _ = component
        return 0.0


@dataclass
class InMemoryRuntimeMetricsSink:
    lock_wait_ms: dict[str, list[float]] = field(default_factory=dict)
    queue_depth: dict[str, list[int]] = field(default_factory=dict)
    queue_lag_ms: dict[str, list[float]] = field(default_factory=dict)
    outbox_retries: dict[str, int] = field(default_factory=dict)
    dlq_count: dict[str, int] = field(default_factory=dict)
    throughput: dict[str, int] = field(default_factory=dict)

    def observe_lock_wait_ms(self, *, component: str, value_ms: float) -> None:
        self.lock_wait_ms.setdefault(component, []).append(float(value_ms))

    def observe_queue_depth(self, *, component: str, value: int) -> None:
        self.queue_depth.setdefault(component, []).append(int(value))

    def observe_queue_lag_ms(self, *, component: str, value_ms: float) -> None:
        self.queue_lag_ms.setdefault(component, []).append(float(value_ms))

    def increment_outbox_retry(self, *, component: str, count: int) -> None:
        self.outbox_retries[component] = int(self.outbox_retries.get(component, 0)) + int(count)

    def increment_dlq(self, *, component: str, count: int) -> None:
        self.dlq_count[component] = int(self.dlq_count.get(component, 0)) + int(count)

    def observe_worker_throughput(self, *, component: str, count: int) -> None:
        self.throughput[component] = int(self.throughput.get(component, 0)) + int(count)

    def lock_wait_p95(self, component: str) -> float:
        values = sorted(self.lock_wait_ms.get(component, []))
        if not values:
            return 0.0
        index = max(0, int(round(0.95 * (len(values) - 1))))
        return float(values[index])

    def queue_lag_p95(self, component: str) -> float:
        values = sorted(self.queue_lag_ms.get(component, []))
        if not values:
            return 0.0
        index = max(0, int(round(0.95 * (len(values) - 1))))
        return float(values[index])


_METRICS_LOCK = Lock()
_METRICS_SINK: RuntimeMetricsSink = NoOpRuntimeMetricsSink()


def set_runtime_metrics_sink(sink: RuntimeMetricsSink) -> None:
    global _METRICS_SINK
    with _METRICS_LOCK:
        _METRICS_SINK = sink


def runtime_metrics() -> RuntimeMetricsSink:
    with _METRICS_LOCK:
        return _METRICS_SINK
