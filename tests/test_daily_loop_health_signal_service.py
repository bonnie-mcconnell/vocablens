from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services import daily_loop_health_signal_service as daily_loop_health_module
from vocablens.services.daily_loop_health_signal_service import DailyLoopHealthSignalService


class FakeDailyLoopHealthStatesRepo:
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


class FakeEngagementStatesRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_all(self):
        return list(self.rows)


class FakeDailyMissionsRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_all(self, limit: int | None = None):
        if limit is None:
            return list(self.rows)
        return list(self.rows)[:limit]


class FakeRewardChestsRepo:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_all(self, limit: int | None = None):
        if limit is None:
            return list(self.rows)
        return list(self.rows)[:limit]


class FakeUOW:
    def __init__(self, *, engagement_states, daily_missions, reward_chests):
        self.engagement_states = FakeEngagementStatesRepo(engagement_states)
        self.daily_missions = FakeDailyMissionsRepo(daily_missions)
        self.reward_chests = FakeRewardChestsRepo(reward_chests)
        self.daily_loop_health_states = FakeDailyLoopHealthStatesRepo()
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


def test_daily_loop_health_signal_service_persists_warning_state(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(daily_loop_health_module, "logger", logger)

    now = daily_loop_health_module.utc_now()
    uow = FakeUOW(
        engagement_states=[
            SimpleNamespace(user_id=1, sessions_last_3_days=2, shields_used_this_week=0),
            SimpleNamespace(user_id=2, sessions_last_3_days=1, shields_used_this_week=0),
            SimpleNamespace(user_id=3, sessions_last_3_days=1, shields_used_this_week=0),
            SimpleNamespace(user_id=4, sessions_last_3_days=2, shields_used_this_week=0),
            SimpleNamespace(user_id=5, sessions_last_3_days=1, shields_used_this_week=0),
            SimpleNamespace(user_id=6, sessions_last_3_days=1, shields_used_this_week=0),
            SimpleNamespace(user_id=7, sessions_last_3_days=1, shields_used_this_week=0),
            SimpleNamespace(user_id=8, sessions_last_3_days=1, shields_used_this_week=0),
            SimpleNamespace(user_id=9, sessions_last_3_days=1, shields_used_this_week=0),
            SimpleNamespace(user_id=10, sessions_last_3_days=1, shields_used_this_week=0),
            SimpleNamespace(user_id=11, sessions_last_3_days=1, shields_used_this_week=0),
            SimpleNamespace(user_id=12, sessions_last_3_days=1, shields_used_this_week=0),
        ],
        daily_missions=[
            SimpleNamespace(user_id=idx, mission_date=now.date().isoformat(), status="issued", created_at=now)
            for idx in range(1, 11)
        ],
        reward_chests=[],
    )
    service = DailyLoopHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))

    assert report["health"]["status"] == "warning"
    state = uow.daily_loop_health_states.rows["global"]
    assert state.metrics["mission_issue_coverage_percent"] == 83.33
    assert "mission_issue_coverage_low" in state.latest_alert_codes
    assert uow.commit_count == 3
    assert alert_metric.records[0]["labels"]["code"] == "mission_issue_coverage_low"
    assert logger.records[0]["message"] == "daily_loop_health_alert"
    assert alert_sink.records[0]["alert_type"] == "daily_loop_health_alert"


def test_daily_loop_health_signal_service_dashboard_orders_attention():
    uow = FakeUOW(engagement_states=[], daily_missions=[], reward_chests=[])
    uow.daily_loop_health_states.rows = {
        "global": SimpleNamespace(
            scope_key="global",
            current_status="warning",
            latest_alert_codes=["mission_issue_coverage_low"],
            metrics={"mission_issue_coverage_percent": 83.33},
            last_evaluated_at=SimpleNamespace(isoformat=lambda: "2026-03-25T08:12:00"),
        ),
    }
    service = DailyLoopHealthSignalService(lambda: uow)

    report = run_async(service.get_health_dashboard(limit=10))

    assert report["summary"]["counts_by_health_status"]["warning"] == 1
    assert report["summary"]["alert_counts_by_code"]["mission_issue_coverage_low"] == 1
    assert report["attention"][0]["scope_key"] == "global"
    assert report["attention"][0]["alert_drilldowns"] == {}


def test_daily_loop_health_signal_service_detects_reward_mission_drift(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(daily_loop_health_module, "DAILY_LOOP_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(daily_loop_health_module, "logger", logger)

    now = daily_loop_health_module.utc_now()
    uow = FakeUOW(
        engagement_states=[SimpleNamespace(user_id=1, sessions_last_3_days=1, shields_used_this_week=0)],
        daily_missions=[SimpleNamespace(id=11, user_id=1, mission_date=now.date().isoformat(), status="completed", created_at=now)],
        reward_chests=[SimpleNamespace(user_id=2, mission_id=11, unlocked_at=now)],
    )
    service = DailyLoopHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))
    dashboard = run_async(service.get_health_dashboard(limit=10))

    assert report["health"]["status"] == "critical"
    assert report["health"]["metrics"]["reward_mission_mismatches"] == 1
    assert "reward_mission_reference_mismatch_detected" in uow.daily_loop_health_states.rows["global"].latest_alert_codes
    drilldown = dashboard["attention"][0]["alert_drilldowns"]["reward_mission_reference_mismatch_detected"]
    assert drilldown[0]["artifact_type"] == "reward_chest"
    assert drilldown[0]["remediation_endpoint"] == "/admin/daily-loop/health/remediate"
