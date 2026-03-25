from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services import exercise_template_health_signal_service as health_module
from vocablens.services.exercise_template_health_signal_service import ExerciseTemplateHealthSignalService


class FakeExerciseTemplateHealthStatesRepo:
    def __init__(self):
        self.rows = {}

    async def get(self, scope_key: str):
        return self.rows.get(scope_key)

    async def list_all(self):
        return list(self.rows.values())

    async def upsert(self, *, scope_key: str, current_status: str, latest_alert_codes: list[str], metrics: dict):
        row = self.rows.get(scope_key)
        if row is None:
            row = SimpleNamespace(
                scope_key=scope_key,
                current_status=current_status,
                latest_alert_codes=list(latest_alert_codes),
                metrics=dict(metrics),
                last_evaluated_at=utc_now(),
            )
            self.rows[scope_key] = row
            return row
        row.current_status = current_status
        row.latest_alert_codes = list(latest_alert_codes)
        row.metrics = dict(metrics)
        row.last_evaluated_at = utc_now()
        return row


class FakeExerciseTemplateRepo:
    def __init__(self):
        self.rows = [
            SimpleNamespace(
                template_key="recall_fill_blank_v1",
                exercise_type="fill_blank",
                objective="recall",
                difficulty="medium",
                status="active",
            ),
            SimpleNamespace(
                template_key="discrimination_choice_v1",
                exercise_type="multiple_choice",
                objective="discrimination",
                difficulty="medium",
                status="draft",
            ),
            SimpleNamespace(
                template_key="correction_fill_blank_v1",
                exercise_type="fill_blank",
                objective="correction",
                difficulty="hard",
                status="archived",
            ),
        ]

    async def list_all(self):
        return list(self.rows)


class FakeExerciseTemplateAuditRepo:
    def __init__(self):
        now = utc_now()
        self.rows = [
            SimpleNamespace(
                template_key="recall_fill_blank_v1",
                change_note="Promoted after fixture review.",
                fixture_report={"fixtures": [{"status": "passed"}]},
                created_at=now - timedelta(days=1),
            ),
            SimpleNamespace(
                template_key="discrimination_choice_v1",
                change_note="Fixture left one rejection in draft.",
                fixture_report={"fixtures": [{"status": "passed"}, {"status": "rejected"}]},
                created_at=now - timedelta(hours=12),
            ),
        ]

    async def latest_for_template(self, template_key: str):
        matches = [row for row in self.rows if row.template_key == template_key]
        return matches[-1] if matches else None

    async def list_by_template(self, template_key: str, limit: int = 50):
        matches = [row for row in self.rows if row.template_key == template_key]
        return list(reversed(matches))[:limit]


class FakeContentQualityChecksRepo:
    def __init__(self):
        now = utc_now()
        self.rows = [
            SimpleNamespace(
                artifact_type="generated_lesson",
                status="passed",
                artifact_summary={"template_keys": ["recall_fill_blank_v1"]},
                checked_at=now - timedelta(hours=10),
            ),
            SimpleNamespace(
                artifact_type="generated_lesson",
                status="rejected",
                artifact_summary={"template_keys": ["recall_fill_blank_v1", "discrimination_choice_v1"]},
                checked_at=now - timedelta(hours=6),
            ),
            SimpleNamespace(
                artifact_type="generated_lesson",
                status="passed",
                artifact_summary={"template_keys": ["correction_fill_blank_v1"]},
                checked_at=now - timedelta(hours=5),
            ),
        ]

    async def list_since(self, since, limit: int = 5000):
        rows = [row for row in self.rows if row.checked_at >= since]
        return rows[:limit]


class FakeUOW:
    def __init__(self):
        self.exercise_templates = FakeExerciseTemplateRepo()
        self.exercise_template_audits = FakeExerciseTemplateAuditRepo()
        self.content_quality_checks = FakeContentQualityChecksRepo()
        self.exercise_template_health_states = FakeExerciseTemplateHealthStatesRepo()
        self.commit_count = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        self.commit_count += 1


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


def test_exercise_template_health_signal_service_persists_scope_states(monkeypatch):
    status_metric = FakeMetric()
    rate_metric = FakeMetric()
    transition_metric = FakeMetric()
    alert_metric = FakeMetric()
    scope_count_metric = FakeMetric()
    active_alert_metric = FakeMetric()
    logger = FakeLogger()
    alert_sink = FakeAlertSink()

    monkeypatch.setattr(health_module, "EXERCISE_TEMPLATE_HEALTH_STATUS", status_metric)
    monkeypatch.setattr(health_module, "EXERCISE_TEMPLATE_HEALTH_RATE", rate_metric)
    monkeypatch.setattr(health_module, "EXERCISE_TEMPLATE_HEALTH_TRANSITIONS", transition_metric)
    monkeypatch.setattr(health_module, "EXERCISE_TEMPLATE_HEALTH_ALERTS", alert_metric)
    monkeypatch.setattr(health_module, "EXERCISE_TEMPLATE_HEALTH_SCOPES", scope_count_metric)
    monkeypatch.setattr(health_module, "EXERCISE_TEMPLATE_ACTIVE_ALERTS", active_alert_metric)
    monkeypatch.setattr(health_module, "logger", logger)

    uow = FakeUOW()
    service = ExerciseTemplateHealthSignalService(lambda: uow, alert_sink=alert_sink)

    report = run_async(service.evaluate_scope("global"))

    assert report["health"]["status"] == "critical"
    assert uow.exercise_template_health_states.rows["global"].current_status == "critical"
    assert uow.exercise_template_health_states.rows["discrimination_choice_v1"].current_status == "warning"
    assert uow.exercise_template_health_states.rows["correction_fill_blank_v1"].current_status == "critical"
    assert "inactive_template_overuse" in uow.exercise_template_health_states.rows["correction_fill_blank_v1"].latest_alert_codes
    assert uow.commit_count == 3
    assert any(record["labels"]["scope_key"] == "global" for record in status_metric.records)
    assert any(record["labels"]["scope_key"] == "global" for record in alert_metric.records)
    assert logger.records[0]["message"] == "exercise_template_health_alert"
    assert alert_sink.records[0]["alert_type"] == "exercise_template_health_alert"


def test_exercise_template_health_signal_service_dashboard_includes_health_summary():
    uow = FakeUOW()
    now = utc_now()
    uow.exercise_template_health_states.rows = {
        "global": SimpleNamespace(
            scope_key="global",
            current_status="warning",
            latest_alert_codes=["inactive_template_overuse"],
            metrics={
                "templates_with_failed_fixtures": 1,
                "templates_with_runtime_rejections": 2,
            },
            last_evaluated_at=now,
        ),
        "recall_fill_blank_v1": SimpleNamespace(
            scope_key="recall_fill_blank_v1",
            current_status="warning",
            latest_alert_codes=["template_runtime_rejection_rate_high"],
            metrics={
                "runtime_usage_count_7d": 2,
                "runtime_rejection_count_7d": 1,
                "latest_failed_fixture_count": 0,
            },
            last_evaluated_at=now - timedelta(minutes=2),
        ),
        "discrimination_choice_v1": SimpleNamespace(
            scope_key="discrimination_choice_v1",
            current_status="critical",
            latest_alert_codes=["fixture_regression_detected"],
            metrics={
                "runtime_usage_count_7d": 1,
                "runtime_rejection_count_7d": 1,
                "latest_failed_fixture_count": 1,
            },
            last_evaluated_at=now - timedelta(minutes=1),
        ),
        "correction_fill_blank_v1": SimpleNamespace(
            scope_key="correction_fill_blank_v1",
            current_status="critical",
            latest_alert_codes=["inactive_template_overuse"],
            metrics={
                "runtime_usage_count_7d": 1,
                "runtime_rejection_count_7d": 0,
                "latest_failed_fixture_count": 0,
            },
            last_evaluated_at=now - timedelta(minutes=3),
        ),
    }
    service = ExerciseTemplateHealthSignalService(lambda: uow)

    report = run_async(service.get_health_dashboard(limit=10))

    assert report["summary"]["counts_by_status"] == {"active": 1, "archived": 1, "draft": 1}
    assert report["summary"]["counts_by_health_status"]["critical"] == 2
    assert report["summary"]["templates_with_alerts"] == 3
    assert report["summary"]["alert_counts_by_code"]["fixture_regression_detected"] == 1
    assert report["attention"][0]["template_key"] == "discrimination_choice_v1"
    assert report["templates"][0]["health_status"] == "critical"
