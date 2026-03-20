from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.business_metrics_service import BusinessMetricsService


class FakeUsersRepo:
    def __init__(self, users):
        self.users = users

    async def list_all(self):
        return self.users


class FakeSubscriptionsRepo:
    def __init__(self, subscriptions):
        self.subscriptions = subscriptions

    async def get_by_user(self, user_id: int):
        return self.subscriptions.get(user_id)


class FakeUOW:
    def __init__(self, users, subscriptions):
        self.users = FakeUsersRepo(users)
        self.subscriptions = FakeSubscriptionsRepo(subscriptions)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


class FakeAnalyticsService:
    async def retention_report(self):
        return {
            "cohorts": [
                {
                    "cohort_date": "2026-03-01",
                    "size": 10,
                    "d1_retention": 70.0,
                    "d7_retention": 40.0,
                    "d30_retention": 25.0,
                    "retention_curve": {"d1": 70.0, "d7": 40.0, "d30": 25.0},
                }
            ],
            "churn_rate": 35.0,
        }


class FakeConversionFunnelService:
    async def metrics(self):
        return {
            "stages": [
                {"stage": "awareness", "users": 100, "conversion_rate": 20.0, "drop_off_rate": 30.0},
                {"stage": "conversion", "users": 20, "conversion_rate": 100.0, "drop_off_rate": 0.0},
            ]
        }


def test_business_metrics_service_builds_revenue_funnel_and_retention_dashboard():
    users = [
        SimpleNamespace(id=1),
        SimpleNamespace(id=2),
        SimpleNamespace(id=3),
    ]
    subscriptions = {
        1: SimpleNamespace(tier="pro", trial_tier=None, trial_ends_at=None),
        2: SimpleNamespace(tier="premium", trial_tier=None, trial_ends_at=None),
        3: SimpleNamespace(tier="free", trial_tier="pro", trial_ends_at=object()),
    }
    service = BusinessMetricsService(
        lambda: FakeUOW(users, subscriptions),
        FakeAnalyticsService(),
        FakeConversionFunnelService(),
    )

    dashboard = run_async(service.dashboard())

    assert dashboard["revenue"]["mrr"] == 70.0
    assert dashboard["revenue"]["arpu"] == 35.0
    assert dashboard["revenue"]["arpu_all_users"] == 23.33
    assert dashboard["revenue"]["ltv"] > 0
    assert dashboard["funnel"]["conversion_per_stage"][0]["stage"] == "awareness"
    assert dashboard["retention_visualization"]["curves"][0]["points"][1]["day"] == 7
    assert dashboard["retention_visualization"]["curves"][0]["points"][1]["retention"] == 40.0
