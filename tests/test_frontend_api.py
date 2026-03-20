from fastapi.testclient import TestClient

from tests.conftest import make_user
from vocablens.api.dependencies import (
    get_admin_token,
    get_analytics_service,
    get_current_user,
    get_experiment_results_service,
    get_frontend_service,
    get_subscription_service,
)
from vocablens.main import create_app


class FakeFrontendService:
    async def dashboard(self, user_id: int):
        return {
            "progress": {
                "vocabulary_total": 12,
                "due_reviews": 3,
                "streak": 4,
                "session_frequency": 2.5,
                "retention_state": "active",
                "metrics": {
                    "vocabulary_mastery_percent": 58.3,
                    "accuracy_rate": 81.0,
                    "response_speed_seconds": 14.2,
                    "fluency_score": 63.0,
                },
                "daily": {"words_learned": 2, "reviews_completed": 4, "messages_sent": 3, "accuracy_rate": 80.0},
                "weekly": {"words_learned": 8, "reviews_completed": 15, "messages_sent": 11, "accuracy_rate": 82.0},
                "trends": {"weekly_words_learned_delta": 3, "weekly_reviews_completed_delta": 4, "weekly_messages_sent_delta": 2, "weekly_accuracy_rate_delta": 5.0, "fluency_score": 63.0},
                "skill_breakdown": {"grammar": 70.0, "vocabulary": 60.0, "fluency": 63.0},
            },
            "subscription": {"tier": "pro", "tutor_depth": "standard", "explanation_quality": "standard", "personalization_level": "standard"},
            "skills": {"grammar": 0.7, "vocabulary": 0.6},
            "next_action": {"action": "review_word", "target": "hola", "reason": "Due review", "difficulty": "medium", "content_type": "vocab"},
            "retention": {"state": "active", "drop_off_risk": 0.2, "actions": []},
            "weak_areas": {"clusters": [], "mistakes": []},
            "roadmap": {"review_words": 3},
        }

    async def recommendations(self, user_id: int):
        return {
            "next_action": {"action": "learn_new_word", "target": "travel", "reason": "Weak cluster", "difficulty": "medium", "content_type": "vocab"},
            "retention_actions": [{"kind": "review_reminder", "reason": "3 reviews waiting", "target": "hola"}],
        }

    async def weak_areas(self, user_id: int):
        return {
            "weak_skills": [{"skill": "vocabulary", "score": 0.55}],
            "weak_clusters": [{"cluster": "travel", "weakness": 1.1, "words": ["hola", "adios"]}],
            "mistake_patterns": [{"category": "grammar", "pattern": "verb tense", "count": 2}],
        }

    async def paywall(self, user_id: int):
        return {
            "show": True,
            "type": "soft_paywall",
            "reason": "usage pressure high",
            "usage_percent": 82,
            "trial_active": False,
            "allow_access": True,
        }

    def meta(self, *, source: str, difficulty: str | None = None, next_action: str | None = None):
        meta = {"source": source}
        if difficulty:
            meta["difficulty"] = difficulty
        if next_action:
            meta["next_action"] = next_action
        return meta


class FakeSubscriptionService:
    async def conversion_metrics(self):
        return {"tier_upgraded": 4, "feature_gate_blocked": 9}


class FakeAnalyticsService:
    async def retention_report(self):
        return {"cohorts": [{"cohort_date": "2026-03-01", "d1_retention": 60.0}]}

    async def usage_report(self):
        return {"dau": 12, "mau": 40, "dau_mau_ratio": 0.3}


class FakeExperimentResultsService:
    async def results(self, experiment_key: str | None = None):
        return {
            "experiments": [
                {
                    "experiment_key": experiment_key or "paywall_offer",
                    "variants": [{"variant": "control", "retention_rate": 40.0, "conversion_rate": 10.0, "engagement": {"sessions_per_user": 1.5}}],
                    "comparisons": [],
                }
            ]
        }


def test_frontend_dashboard_and_related_endpoints_return_standardized_envelopes():
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_frontend_service] = lambda: FakeFrontendService()
    client = TestClient(app)

    dashboard = client.get("/frontend/dashboard", headers={"Authorization": "Bearer ignored"})
    recommendations = client.get("/frontend/recommendations", headers={"Authorization": "Bearer ignored"})
    weak_areas = client.get("/frontend/weak-areas", headers={"Authorization": "Bearer ignored"})
    paywall = client.get("/frontend/paywall", headers={"Authorization": "Bearer ignored"})

    assert dashboard.status_code == 200
    assert dashboard.json()["meta"]["source"] == "frontend.dashboard"
    assert dashboard.json()["data"]["next_action"]["action"] == "review_word"
    assert dashboard.json()["data"]["progress"]["metrics"]["accuracy_rate"] == 81.0

    assert recommendations.status_code == 200
    assert recommendations.json()["meta"]["next_action"] == "learn_new_word"
    assert recommendations.json()["data"]["retention_actions"][0]["kind"] == "review_reminder"

    assert weak_areas.status_code == 200
    assert weak_areas.json()["meta"]["source"] == "frontend.weak_areas"
    assert weak_areas.json()["data"]["weak_clusters"][0]["cluster"] == "travel"

    assert paywall.status_code == 200
    assert paywall.json()["meta"]["source"] == "frontend.paywall"
    assert paywall.json()["data"]["type"] == "soft_paywall"


def test_admin_conversion_report_is_protected_and_standardized():
    app = create_app()
    app.dependency_overrides[get_admin_token] = lambda: "ok"
    app.dependency_overrides[get_subscription_service] = lambda: FakeSubscriptionService()
    app.dependency_overrides[get_analytics_service] = lambda: FakeAnalyticsService()
    app.dependency_overrides[get_experiment_results_service] = lambda: FakeExperimentResultsService()
    client = TestClient(app)

    response = client.get("/admin/reports/conversions", headers={"X-Admin-Token": "secret"})
    retention = client.get("/admin/analytics/retention", headers={"X-Admin-Token": "secret"})
    usage = client.get("/admin/analytics/usage", headers={"X-Admin-Token": "secret"})
    experiments = client.get("/admin/experiments/results?experiment_key=paywall_offer", headers={"X-Admin-Token": "secret"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["source"] == "admin.conversions"
    assert payload["data"]["conversion_metrics"]["tier_upgraded"] == 4
    assert retention.status_code == 200
    assert retention.json()["meta"]["source"] == "admin.analytics.retention"
    assert retention.json()["data"]["retention"]["cohorts"][0]["d1_retention"] == 60.0
    assert usage.status_code == 200
    assert usage.json()["meta"]["source"] == "admin.analytics.usage"
    assert usage.json()["data"]["usage"]["dau"] == 12
    assert experiments.status_code == 200
    assert experiments.json()["meta"]["source"] == "admin.experiments.results"
    assert experiments.json()["data"]["experiment_results"]["experiments"][0]["experiment_key"] == "paywall_offer"
