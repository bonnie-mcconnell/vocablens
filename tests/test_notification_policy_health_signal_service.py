from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services import notification_policy_health_signal_service as health_signal_module
from vocablens.services.notification_policy_health_signal_service import NotificationPolicyHealthSignalService


class FakeNotificationPolicyHealthStatesRepo:
    def __init__(self):
        self.rows = {}

    async def get(self, policy_key: str):
        return self.rows.get(policy_key)

    async def list_all(self):
        return list(self.rows.values())

    async def upsert(
        self,
        *,
        policy_key: str,
        current_status: str,
        latest_alert_codes: list[str],
        metrics: dict,
    ):
        row = self.rows.get(policy_key)
        if row is None:
            row = SimpleNamespace(
                policy_key=policy_key,
                current_status=current_status,
                latest_alert_codes=list(latest_alert_codes),
                metrics=dict(metrics),
            )
            self.rows[policy_key] = row
            return row
        row.current_status = current_status
        row.latest_alert_codes = list(latest_alert_codes)
        row.metrics = dict(metrics)
        return row


class FakeUOW:
    def __init__(self):
        self.notification_policy_health_states = FakeNotificationPolicyHealthStatesRepo()
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


class FakeRegistryService:
    def __init__(self, reports: list[dict]):
        self._reports = list(reports)
        self.calls = []

    async def get_operator_report(self, policy_key: str, *, limit: int = 100):
        self.calls.append((policy_key, limit))
        if len(self.calls) <= len(self._reports):
            return self._reports[len(self.calls) - 1]
        return self._reports[-1]


class FakeMetricHandle:
    def __init__(self, records: list[dict], labels: dict[str, str]):
        self._records = records
        self._labels = labels

    def set(self, value: float):
        self._records.append({"op": "set", "labels": dict(self._labels), "value": value})

    def inc(self, value: float = 1.0):
        self._records.append({"op": "inc", "labels": dict(self._labels), "value": value})


class FakeMetric:
    def __init__(self):
        self.records = []

    def labels(self, **labels):
        return FakeMetricHandle(self.records, labels)


class FakeLogger:
    def __init__(self):
        self.records = []

    def warning(self, message: str, *, extra: dict):
        self.records.append({"message": message, "extra": dict(extra)})


class FakeAlertSink:
    def __init__(self):
        self.records = []

    async def emit(self, alert_type: str, payload: dict):
        self.records.append({"alert_type": alert_type, "payload": dict(payload)})


def _report(status: str, alerts: list[dict], metrics: dict) -> dict:
    return {
        "policy": {"policy_key": "default"},
        "health": {
            "status": status,
            "metrics": dict(metrics),
            "alerts": list(alerts),
        },
    }


def test_notification_policy_health_signal_service_persists_state_and_records_metrics(monkeypatch):
    uow = FakeUOW()
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    policy_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_POLICIES", policy_count_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(health_signal_module, "logger", logger)

    service = NotificationPolicyHealthSignalService(lambda: uow, alert_sink=alert_sink)
    service._registry_service = FakeRegistryService(
        [
            _report(
                "warning",
                [
                    {
                        "code": "suppression_rate_high",
                        "severity": "warning",
                    }
                ],
                {
                    "failed_delivery_rate_percent": 10.0,
                    "suppression_rate_percent": 66.7,
                },
            )
        ]
    )

    report = run_async(service.evaluate_policy("default"))

    assert report["health"]["status"] == "warning"
    state = uow.notification_policy_health_states.rows["default"]
    assert state.current_status == "warning"
    assert state.latest_alert_codes == ["suppression_rate_high"]
    assert state.metrics["suppression_rate_percent"] == 66.7
    assert uow.commit_count == 1
    assert status_metric.records == [
        {"op": "set", "labels": {"policy_key": "default", "status": "healthy"}, "value": 0},
        {"op": "set", "labels": {"policy_key": "default", "status": "warning"}, "value": 1},
        {"op": "set", "labels": {"policy_key": "default", "status": "critical"}, "value": 0},
    ]
    assert rate_metric.records == [
        {
            "op": "set",
            "labels": {"policy_key": "default", "metric": "failed_delivery_rate_percent"},
            "value": 10.0,
        },
        {
            "op": "set",
            "labels": {"policy_key": "default", "metric": "suppression_rate_percent"},
            "value": 66.7,
        },
    ]
    assert transition_metric.records == []
    assert alert_metric.records == [
        {
            "op": "inc",
            "labels": {
                "policy_key": "default",
                "code": "suppression_rate_high",
                "severity": "warning",
            },
            "value": 1.0,
        }
    ]
    assert policy_count_metric.records == [
        {"op": "set", "labels": {"status": "healthy"}, "value": 0.0},
        {"op": "set", "labels": {"status": "warning"}, "value": 1.0},
        {"op": "set", "labels": {"status": "critical"}, "value": 0.0},
    ]
    assert active_alert_metric.records[-2:] == [
        {"op": "set", "labels": {"policy_key": "default", "severity": "warning"}, "value": 1.0},
        {"op": "set", "labels": {"policy_key": "default", "severity": "critical"}, "value": 0.0},
    ]
    assert alert_sink.records == [
        {
            "alert_type": "notification_policy_health_alert",
            "payload": {
                "policy_key": "default",
                "code": "suppression_rate_high",
                "severity": "warning",
                "alert": {"code": "suppression_rate_high", "severity": "warning"},
                "metrics": {
                    "failed_delivery_rate_percent": 10.0,
                    "suppression_rate_percent": 66.7,
                },
            },
        }
    ]
    assert logger.records == [
        {
            "message": "notification_policy_health_alert",
            "extra": {
                "policy_key": "default",
                "code": "suppression_rate_high",
                "severity": "warning",
                "alert": {"code": "suppression_rate_high", "severity": "warning"},
                "metrics": {
                    "failed_delivery_rate_percent": 10.0,
                    "suppression_rate_percent": 66.7,
                },
            },
        }
    ]


def test_notification_policy_health_signal_service_emits_transition_only_when_state_changes(monkeypatch):
    uow = FakeUOW()
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    policy_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_HEALTH_POLICIES", policy_count_metric)
    monkeypatch.setattr(health_signal_module, "NOTIFICATION_POLICY_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(health_signal_module, "logger", logger)

    service = NotificationPolicyHealthSignalService(lambda: uow, alert_sink=alert_sink)
    service._registry_service = FakeRegistryService(
        [
            _report(
                "healthy",
                [],
                {
                    "failed_delivery_rate_percent": 1.0,
                    "suppression_rate_percent": 5.0,
                },
            ),
            _report(
                "critical",
                [
                    {
                        "code": "failed_delivery_rate_high",
                        "severity": "critical",
                    }
                ],
                {
                    "failed_delivery_rate_percent": 48.0,
                    "suppression_rate_percent": 12.0,
                },
            ),
            _report(
                "critical",
                [
                    {
                        "code": "failed_delivery_rate_high",
                        "severity": "critical",
                    }
                ],
                {
                    "failed_delivery_rate_percent": 49.0,
                    "suppression_rate_percent": 12.0,
                },
            ),
        ]
    )

    run_async(service.evaluate_policy("default"))
    run_async(service.evaluate_policy("default"))
    run_async(service.evaluate_policy("default"))

    state = uow.notification_policy_health_states.rows["default"]
    assert state.current_status == "critical"
    assert state.latest_alert_codes == ["failed_delivery_rate_high"]
    assert uow.commit_count == 3
    assert transition_metric.records == [
        {
            "op": "inc",
            "labels": {
                "policy_key": "default",
                "from_status": "healthy",
                "to_status": "critical",
            },
            "value": 1.0,
        }
    ]
    assert alert_metric.records == [
        {
            "op": "inc",
            "labels": {
                "policy_key": "default",
                "code": "failed_delivery_rate_high",
                "severity": "critical",
            },
            "value": 1.0,
        }
    ]
    assert logger.records[0] == {
        "message": "notification_policy_health_transition",
        "extra": {
            "policy_key": "default",
            "from_status": "healthy",
            "to_status": "critical",
            "metrics": {
                "failed_delivery_rate_percent": 48.0,
                "suppression_rate_percent": 12.0,
            },
        },
    }
    assert logger.records[1]["message"] == "notification_policy_health_alert"
    assert alert_sink.records == [
        {
            "alert_type": "notification_policy_health_transition",
            "payload": {
                "policy_key": "default",
                "from_status": "healthy",
                "to_status": "critical",
                "metrics": {
                    "failed_delivery_rate_percent": 48.0,
                    "suppression_rate_percent": 12.0,
                },
            },
        },
        {
            "alert_type": "notification_policy_health_alert",
            "payload": {
                "policy_key": "default",
                "code": "failed_delivery_rate_high",
                "severity": "critical",
                "alert": {"code": "failed_delivery_rate_high", "severity": "critical"},
                "metrics": {
                    "failed_delivery_rate_percent": 48.0,
                    "suppression_rate_percent": 12.0,
                },
            },
        },
    ]
