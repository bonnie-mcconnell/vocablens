from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from tests.conftest import run_async
from tests.postgres_harness import postgres_harness
from tests.product_flow_scenarios import run_comeback_flow, run_first_week_flow
from vocablens.api.dependencies_admin import get_admin_token
from vocablens.api.dependencies_core import get_uow_factory
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.main import create_app


pytestmark = pytest.mark.postgres


def _build_admin_client(harness) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_admin_token] = lambda: "ok"
    app.dependency_overrides[get_uow_factory] = lambda: UnitOfWorkFactory(harness.session_factory)
    return TestClient(app)


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _recent_item_for_user(items: list[dict], user_id: int) -> dict:
    for item in items:
        if int(item["user_id"]) == user_id:
            return item
    raise AssertionError(f"Expected item for user {user_id}")


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


def test_admin_reports_keep_first_week_timeline_and_reference_ids_aligned():
    with postgres_harness() as harness:
        run_async(run_first_week_flow(harness))
        client = _build_admin_client(harness)

        session_report = client.get("/admin/sessions/601/report", headers={"X-Admin-Token": "secret"}).json()["data"]
        lifecycle_report = client.get("/admin/lifecycle/601/report", headers={"X-Admin-Token": "secret"}).json()["data"]
        monetization_report = client.get(
            "/admin/monetization/601/report?geography=us",
            headers={"X-Admin-Token": "secret"},
        ).json()["data"]
        experiment_report = client.get(
            "/admin/experiments/registry/paywall_offer/report?limit=10",
            headers={"X-Admin-Token": "secret"},
        ).json()["data"]["experiment"]

        session_id = session_report["latest_decisions"]["latest_session"]["session_id"]
        session_created_at = _parse_timestamp(session_report["latest_decisions"]["latest_session"]["created_at"])
        session_evaluated_at = _parse_timestamp(session_report["latest_decisions"]["latest_evaluation"]["created_at"])
        lifecycle_decided_at = _parse_timestamp(lifecycle_report["latest_decisions"]["lifecycle_decision"]["created_at"])
        monetization_decided_at = _parse_timestamp(
            monetization_report["latest_decisions"]["monetization_decision"]["created_at"]
        )

        assert session_report["latest_decisions"]["latest_attempt"]["session_id"] == session_id
        assert session_report["latest_decisions"]["latest_evaluation"]["reference_id"] == session_id
        assert lifecycle_report["detail"]["lifecycle_state"]["current_stage"] in {"new_user", "activating"}
        assert lifecycle_report["detail"]["notification_eligibility"]["lifecycle_stage"] == lifecycle_report["detail"]["lifecycle_state"]["current_stage"]
        assert monetization_report["detail"]["monetization_state"]["lifecycle_stage"] == lifecycle_report["detail"]["lifecycle_state"]["current_stage"]
        assert monetization_report["latest_decisions"]["lifecycle_decision"]["id"] == lifecycle_report["latest_decisions"]["lifecycle_decision"]["id"]

        assignment = _recent_item_for_user(experiment_report["recent_assignments"], 601)
        exposure = _recent_item_for_user(experiment_report["recent_exposures"], 601)
        attribution = _recent_item_for_user(experiment_report["recent_attributions"], 601)
        assignment_at = _parse_timestamp(assignment["assigned_at"])
        exposed_at = _parse_timestamp(exposure["exposed_at"])
        window_end_at = _parse_timestamp(attribution["window_end_at"])

        assert assignment["variant"] == exposure["variant"] == attribution["variant"]
        assert experiment_report["latest_assignment_trace"]["reference_id"] == "paywall_offer"
        assert assignment_at is not None and exposed_at is not None and window_end_at is not None
        assert session_created_at is not None and session_evaluated_at is not None
        assert lifecycle_decided_at is not None and monetization_decided_at is not None
        assert session_created_at <= session_evaluated_at <= lifecycle_decided_at <= monetization_decided_at
        assert assignment_at <= exposed_at <= window_end_at


def test_admin_reports_keep_comeback_timeline_and_reference_ids_aligned():
    with postgres_harness() as harness:
        run_async(run_comeback_flow(harness))
        client = _build_admin_client(harness)

        notification_report = client.get(
            "/admin/notifications/602/report?policy_key=default",
            headers={"X-Admin-Token": "secret"},
        ).json()["data"]
        session_report = client.get("/admin/sessions/602/report", headers={"X-Admin-Token": "secret"}).json()["data"]
        lifecycle_report = client.get("/admin/lifecycle/602/report", headers={"X-Admin-Token": "secret"}).json()["data"]
        monetization_report = client.get(
            "/admin/monetization/602/report?geography=us",
            headers={"X-Admin-Token": "secret"},
        ).json()["data"]
        experiment_report = client.get(
            "/admin/experiments/registry/paywall_offer/report?limit=10",
            headers={"X-Admin-Token": "secret"},
        ).json()["data"]["experiment"]

        notification_reference = notification_report["latest_decisions"]["notification_selection"]["reference_id"]
        delivery_reference = notification_report["latest_decisions"]["latest_delivery"]["reference_id"]
        session_id = session_report["latest_decisions"]["latest_session"]["session_id"]
        session_created_at = _parse_timestamp(session_report["latest_decisions"]["latest_session"]["created_at"])
        notification_decided_at = _parse_timestamp(
            notification_report["latest_decisions"]["notification_selection"]["created_at"]
        )
        delivery_created_at = _parse_timestamp(
            notification_report["latest_decisions"]["latest_delivery"]["created_at"]
        )
        conversion_at = _parse_timestamp(
            _recent_item_for_user(experiment_report["recent_attributions"], 602)["first_conversion_at"]
        )
        last_accepted_at = _parse_timestamp(monetization_report["detail"]["monetization_state"]["last_accepted_at"])

        assert session_report["latest_decisions"]["latest_attempt"]["session_id"] == session_id
        assert session_report["latest_decisions"]["latest_evaluation"]["reference_id"] == session_id
        assert notification_reference == delivery_reference == notification_report["detail"]["notification_state"]["last_reference_id"]
        assert notification_reference == lifecycle_report["latest_decisions"]["notification_selection"]["reference_id"]
        assert lifecycle_report["detail"]["notification_eligibility"]["lifecycle_stage"] == lifecycle_report["detail"]["lifecycle_state"]["current_stage"]
        assert monetization_report["detail"]["monetization_state"]["lifecycle_stage"] == lifecycle_report["detail"]["lifecycle_state"]["current_stage"]

        attribution = _recent_item_for_user(experiment_report["recent_attributions"], 602)
        assert attribution["converted"] is True
        assert notification_decided_at is not None and delivery_created_at is not None and session_created_at is not None
        assert last_accepted_at is not None and conversion_at is not None
        assert notification_decided_at <= delivery_created_at <= session_created_at <= last_accepted_at <= conversion_at


def test_admin_notification_report_keeps_selection_and_delivery_payloads_aligned():
    with postgres_harness() as harness:
        run_async(run_comeback_flow(harness))
        client = _build_admin_client(harness)

        report = client.get(
            "/admin/notifications/602/report?policy_key=default",
            headers={"X-Admin-Token": "secret"},
        )

        assert report.status_code == 200
        payload = report.json()["data"]

        latest_selection = payload["latest_decisions"]["notification_selection"]
        latest_delivery = payload["latest_decisions"]["latest_delivery"]
        detail = payload["detail"]
        summary = payload["delivery_summary"]

        assert latest_selection is not None
        assert latest_delivery is not None
        assert detail["notification_deliveries"]
        assert detail["notification_deliveries"][0]["id"] == latest_delivery["id"]

        assert latest_delivery["status"] == "sent"
        assert latest_delivery["reference_id"] == latest_selection["reference_id"]
        assert latest_delivery["source_context"] == latest_selection["source"]
        assert latest_delivery["category"] == latest_selection["outputs"]["message_category"]
        assert latest_delivery["payload"]["channel"] == latest_selection["outputs"]["channel"]

        assert detail["notification_state"]["last_reference_id"] == latest_selection["reference_id"]
        assert detail["notification_state"]["last_delivery_status"] == "sent"
        assert detail["notification_state"]["last_delivery_channel"] == latest_selection["outputs"]["channel"]

        assert summary["counts_by_status"]["sent"] >= 1
        assert summary["counts_by_category"][latest_delivery["category"]] >= 1
        assert summary["counts_by_provider"][latest_delivery["provider"]] >= 1
