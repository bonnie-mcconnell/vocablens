from __future__ import annotations

from typing import Any, Protocol

from vocablens.infrastructure.logging.logger import get_logger


class OpsAlertSink(Protocol):
    async def emit(self, alert_type: str, payload: dict[str, Any]) -> None:
        ...


class NullOpsAlertSink:
    async def emit(self, alert_type: str, payload: dict[str, Any]) -> None:
        return None


class LoggingOpsAlertSink:
    def __init__(self):
        self._logger = get_logger("vocablens.ops_alerts")

    async def emit(self, alert_type: str, payload: dict[str, Any]) -> None:
        self._logger.warning(
            "ops_alert",
            extra={
                "alert_type": alert_type,
                "payload": dict(payload),
            },
        )


class CompositeOpsAlertSink:
    def __init__(self, *sinks: OpsAlertSink):
        self._sinks = tuple(sinks)

    async def emit(self, alert_type: str, payload: dict[str, Any]) -> None:
        for sink in self._sinks:
            await sink.emit(alert_type, payload)
