from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services import monetization_health_signal_service as monetization_health_module
from vocablens.services.monetization_health_signal_service import MonetizationHealthSignalService


class FakeMonetizationHealthStatesRepo:
    def __init__(self):
        self.rows = {}

    async def get(self, scope_key: str):
        return self.rows.get(scope_key)

    async def list_all(self):
        return list(self.rows.values())

    async def upsert(
        self,
        *,
        scope_key: str,
        current_status: str,
        latest_alert_codes: list[str],
        metrics: dict,
    ):
        row = self.rows.get(scope_key)
        if row is None:
            row = SimpleNamespace(
                scope_key=scope_key,
                current_status=current_status,
                latest_alert_codes=list(latest_alert_codes),
                metrics=dict(metrics),
            )
            self.rows[scope_key] = row
            return row
        row.current_status = current_status
        row.latest_alert_codes = list(latest_alert_codes)
        row.metrics = dict(metrics)
        return row


class FakeMonetizationStatesRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_all(self):
        return list(self.rows)


class FakeLifecycleStatesRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_all(self):
        return list(self.rows)


class FakeMonetizationOfferEventsRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_all(self, geography: str | None = None):
        if geography is None:
            return list(self.rows)
        return [row for row in self.rows if str(getattr(row, "geography", "") or "") == geography]


class FakeUOW:
    def __init__(self, *, monetization_states, lifecycle_states, events):
        self.monetization_states = FakeMonetizationStatesRepo(monetization_states)
        self.lifecycle_states = FakeLifecycleStatesRepo(lifecycle_states)
        self.monetization_offer_events = FakeMonetizationOfferEventsRepo(events)
        self.monetization_health_states = FakeMonetizationHealthStatesRepo()
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


class FakeMetricHandle:
    def __init__(self, records, labels):
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


def test_monetization_health_signal_service_detects_lifecycle_stage_drift(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(monetization_health_module, "MONETIZATION_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(monetization_health_module, "MONETIZATION_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(monetization_health_module, "MONETIZATION_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(monetization_health_module, "MONETIZATION_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(monetization_health_module, "MONETIZATION_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(monetization_health_module, "MONETIZATION_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(monetization_health_module, "logger", logger)

    uow = FakeUOW(
        monetization_states=[
            SimpleNamespace(
                user_id=1,
                current_geography="us",
                paywall_impressions=8,
                paywall_dismissals=2,
                paywall_acceptances=1,
                paywall_skips=0,
                fatigue_score=1,
                lifecycle_stage="engaged",
            )
        ],
        lifecycle_states=[SimpleNamespace(user_id=1, current_stage="at_risk")],
        events=[SimpleNamespace(geography="us", created_at=None)],
    )
    service = MonetizationHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))
    dashboard = run_async(service.get_health_dashboard(limit=10))

    assert report["health"]["status"] == "critical"
    assert report["health"]["metrics"]["lifecycle_stage_mismatches"] == 1
    assert "monetization_lifecycle_stage_mismatch_detected" in uow.monetization_health_states.rows["global"].latest_alert_codes
    assert alert_metric.records[0]["labels"]["code"] == "monetization_lifecycle_stage_mismatch_detected"
    drilldown = dashboard["attention"][0]["alert_drilldowns"]["monetization_lifecycle_stage_mismatch_detected"]
    assert drilldown[0]["artifact_type"] == "monetization_state"
    assert drilldown[0]["remediation_endpoint"] == "/admin/monetization/health/remediate"


def test_monetization_health_signal_service_dashboard_orders_attention():
    uow = FakeUOW(monetization_states=[], lifecycle_states=[], events=[])
    uow.monetization_health_states.rows = {
        "global": SimpleNamespace(
            scope_key="global",
            current_status="critical",
            latest_alert_codes=["monetization_lifecycle_stage_mismatch_detected"],
            metrics={"lifecycle_stage_mismatches": 2},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T08:14:00"),
        ),
    }
    service = MonetizationHealthSignalService(lambda: uow)

    report = run_async(service.get_health_dashboard(limit=10))

    assert report["summary"]["counts_by_health_status"]["critical"] == 1
    assert report["attention"][0]["scope_key"] == "global"
    assert report["attention"][0]["alert_drilldowns"] == {}
