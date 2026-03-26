from fastapi.testclient import TestClient

from tests.conftest import run_async
from tests.postgres_harness import postgres_harness
from tests.product_flow_scenarios import run_comeback_flow, run_first_week_flow
from vocablens.api.dependencies import get_admin_token, get_uow_factory
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.main import create_app


def _build_admin_client(harness) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_admin_token] = lambda: "ok"
    app.dependency_overrides[get_uow_factory] = lambda: UnitOfWorkFactory(harness.session_factory)
    return TestClient(app)


def test_admin_diagnostics_follow_first_week_flow_state():
    with postgres_harness() as harness:
        run_async(run_first_week_flow(harness))
        client = _build_admin_client(harness)

        session_report = client.get("/admin/sessions/601/report", headers={"X-Admin-Token": "secret"})
        daily_loop_report = client.get("/admin/daily-loop/601/report", headers={"X-Admin-Token": "secret"})
        lifecycle_report = client.get("/admin/lifecycle/601/report", headers={"X-Admin-Token": "secret"})
        monetization_report = client.get(
            "/admin/monetization/601/report?geography=us",
            headers={"X-Admin-Token": "secret"},
        )
        experiment_report = client.get(
            "/admin/experiments/registry/paywall_offer/report?limit=10",
            headers={"X-Admin-Token": "secret"},
        )

        assert session_report.status_code == 200
        assert session_report.json()["meta"]["source"] == "admin.sessions.report"
        assert session_report.json()["data"]["latest_decisions"]["latest_session"]["status"] == "completed"
        assert session_report.json()["data"]["latest_decisions"]["latest_attempt"]["submission_id"] == "first_week_submit"
        assert session_report.json()["data"]["latest_decisions"]["latest_evaluation"]["trace_type"] == "session_evaluation"

        assert daily_loop_report.status_code == 200
        assert daily_loop_report.json()["meta"]["source"] == "admin.daily_loop.report"
        assert daily_loop_report.json()["data"]["latest_decisions"]["latest_reward_chest"]["status"] == "claimed"
        assert daily_loop_report.json()["data"]["mission_summary"]["counts_by_status"]["completed"] >= 1

        assert lifecycle_report.status_code == 200
        assert lifecycle_report.json()["meta"]["source"] == "admin.lifecycle.report"
        assert lifecycle_report.json()["data"]["detail"]["lifecycle_state"]["current_stage"] in {"new_user", "activating"}
        assert lifecycle_report.json()["data"]["latest_decisions"]["lifecycle_decision"]["trace_type"] == "lifecycle_decision"
        assert (
            lifecycle_report.json()["data"]["detail"]["notification_eligibility"]["lifecycle_stage"]
            == lifecycle_report.json()["data"]["detail"]["lifecycle_state"]["current_stage"]
        )

        assert monetization_report.status_code == 200
        assert monetization_report.json()["meta"]["source"] == "admin.monetization.report"
        assert monetization_report.json()["data"]["latest_decisions"]["monetization_decision"]["trace_type"] == "monetization_decision"
        assert monetization_report.json()["data"]["detail"]["monetization_state"]["trial_started_at"] is not None
        assert monetization_report.json()["data"]["detail"]["subscription"]["trial_tier"] == "pro"

        assert experiment_report.status_code == 200
        assert experiment_report.json()["meta"]["source"] == "admin.experiments.registry.report"
        assert any(
            item["user_id"] == 601
            for item in experiment_report.json()["data"]["experiment"]["recent_assignments"]
        )
        assert any(
            item["user_id"] == 601
            for item in experiment_report.json()["data"]["experiment"]["recent_attributions"]
        )


def test_admin_diagnostics_follow_comeback_flow_state():
    with postgres_harness() as harness:
        run_async(run_comeback_flow(harness))
        client = _build_admin_client(harness)

        notification_report = client.get(
            "/admin/notifications/602/report?policy_key=default",
            headers={"X-Admin-Token": "secret"},
        )
        session_report = client.get("/admin/sessions/602/report", headers={"X-Admin-Token": "secret"})
        daily_loop_report = client.get("/admin/daily-loop/602/report", headers={"X-Admin-Token": "secret"})
        lifecycle_report = client.get("/admin/lifecycle/602/report", headers={"X-Admin-Token": "secret"})
        monetization_report = client.get(
            "/admin/monetization/602/report?geography=us",
            headers={"X-Admin-Token": "secret"},
        )
        experiment_report = client.get(
            "/admin/experiments/registry/paywall_offer/report?limit=10",
            headers={"X-Admin-Token": "secret"},
        )

        assert notification_report.status_code == 200
        assert notification_report.json()["meta"]["source"] == "admin.notifications.report"
        assert notification_report.json()["data"]["latest_decisions"]["notification_selection"]["trace_type"] == "notification_selection"
        assert notification_report.json()["data"]["detail"]["notification_state"]["last_delivery_status"] == "sent"
        assert notification_report.json()["data"]["delivery_summary"]["counts_by_status"]["sent"] >= 1

        assert session_report.status_code == 200
        assert session_report.json()["data"]["latest_decisions"]["latest_session"]["status"] == "completed"
        assert session_report.json()["data"]["latest_decisions"]["latest_attempt"]["submission_id"] == "comeback_submit"

        assert daily_loop_report.status_code == 200
        assert daily_loop_report.json()["data"]["latest_decisions"]["latest_reward_chest"]["status"] == "claimed"
        assert daily_loop_report.json()["data"]["mission_summary"]["counts_by_status"]["completed"] >= 1

        assert lifecycle_report.status_code == 200
        assert lifecycle_report.json()["meta"]["source"] == "admin.lifecycle.report"
        assert lifecycle_report.json()["data"]["detail"]["lifecycle_state"]["current_stage"] in {"at_risk", "churned", "activating"}
        assert lifecycle_report.json()["data"]["latest_decisions"]["notification_selection"]["trace_type"] == "notification_selection"

        assert monetization_report.status_code == 200
        assert monetization_report.json()["meta"]["source"] == "admin.monetization.report"
        assert monetization_report.json()["data"]["detail"]["subscription"]["tier"] == "pro"
        assert monetization_report.json()["data"]["detail"]["monetization_state"]["paywall_acceptances"] >= 1

        assert experiment_report.status_code == 200
        assert any(
            item["user_id"] == 602 and item["converted"] is True
            for item in experiment_report.json()["data"]["experiment"]["recent_attributions"]
        )
