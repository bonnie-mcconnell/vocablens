from datetime import timedelta
from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.services.analytics_service import AnalyticsService


class FakeUsersRepo:
    def __init__(self, users):
        self.users = users

    async def list_all(self):
        return self.users


class FakeEventsRepo:
    def __init__(self, events):
        self.events = events

    async def list_since(self, since, event_types=None, limit: int = 5000):
        filtered = [event for event in self.events if event.created_at >= since]
        if event_types:
            filtered = [event for event in filtered if event.event_type in event_types]
        return filtered[:limit]


class FakeUOW:
    def __init__(self, users, events):
        self.users = FakeUsersRepo(users)
        self.events = FakeEventsRepo(events)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_analytics_service_calculates_daily_cohorts_and_retention_correctly():
    now = utc_now()
    users = [
        SimpleNamespace(id=1, created_at=now - timedelta(days=40)),
        SimpleNamespace(id=2, created_at=now - timedelta(days=40)),
        SimpleNamespace(id=3, created_at=now - timedelta(days=10)),
    ]
    signup_day_old = (now - timedelta(days=40)).date()
    signup_day_new = (now - timedelta(days=10)).date()
    events = [
        SimpleNamespace(user_id=1, event_type="session_started", created_at=now - timedelta(days=39)),
        SimpleNamespace(user_id=1, event_type="session_started", created_at=now - timedelta(days=33)),
        SimpleNamespace(user_id=1, event_type="session_started", created_at=now - timedelta(days=10)),
        SimpleNamespace(user_id=2, event_type="session_started", created_at=now - timedelta(days=39)),
        SimpleNamespace(user_id=3, event_type="session_started", created_at=now - timedelta(days=9)),
        SimpleNamespace(user_id=3, event_type="session_started", created_at=now - timedelta(days=3)),
    ]
    service = AnalyticsService(lambda: FakeUOW(users, events))

    report = run_async(service.retention_report())

    old_cohort = next(row for row in report.cohorts if row.cohort_date == signup_day_old.isoformat())
    new_cohort = next(row for row in report.cohorts if row.cohort_date == signup_day_new.isoformat())

    assert old_cohort.size == 2
    assert old_cohort.d1_retention == 100.0
    assert old_cohort.d7_retention == 50.0
    assert old_cohort.d30_retention == 50.0
    assert new_cohort.size == 1
    assert new_cohort.d1_retention == 100.0
    assert new_cohort.d7_retention == 100.0


def test_analytics_service_computes_usage_and_retention_metrics():
    now = utc_now()
    users = [SimpleNamespace(id=1, created_at=now - timedelta(days=5))]
    events = [
        SimpleNamespace(user_id=1, event_type="session_started", created_at=now - timedelta(minutes=10)),
        SimpleNamespace(user_id=1, event_type="session_ended", created_at=now - timedelta(minutes=5)),
        SimpleNamespace(user_id=1, event_type="session_started", created_at=now - timedelta(days=2)),
        SimpleNamespace(user_id=1, event_type="session_ended", created_at=now - timedelta(days=2, minutes=-7)),
        SimpleNamespace(user_id=1, event_type="message_sent", created_at=now - timedelta(days=1)),
    ]
    service = AnalyticsService(lambda: FakeUOW(users, events))

    usage = run_async(service.usage_report())

    assert usage.dau == 1
    assert usage.mau == 1
    assert usage.dau_mau_ratio == 1.0
    assert usage.avg_session_length_seconds == 360.0
    assert usage.sessions_per_user == 2.0
    assert usage.engagement_distribution.low == 1
