from tests.conftest import run_async
from tests.postgres_harness import postgres_harness
from tests.product_flow_scenarios import run_comeback_flow, run_first_week_flow


def test_first_week_flow_persists_canonical_cross_system_state():
    with postgres_harness() as harness:
        snapshot = run_async(run_first_week_flow(harness))

        assert snapshot.session.status == "completed"
        assert snapshot.engagement_state.total_sessions >= 1
        assert snapshot.daily_missions[0].status == "completed"
        assert snapshot.reward_chests[0].status == "claimed"
        assert snapshot.lifecycle_state is not None
        assert snapshot.lifecycle_state.current_stage in {"new_user", "activating"}
        assert snapshot.notification_state is not None
        assert snapshot.notification_state.lifecycle_stage == snapshot.lifecycle_state.current_stage
        assert snapshot.monetization_state.paywall_impressions >= 1
        assert snapshot.monetization_state.trial_started_at is not None
        assert snapshot.subscription is not None
        assert snapshot.subscription.trial_tier == "pro"
        assert len(snapshot.experiment_assignments) >= 1
        assert len(snapshot.experiment_exposures) >= 1
        assert len(snapshot.experiment_attributions) >= 1
        trace_types = {row.trace_type for row in snapshot.traces}
        assert "session_evaluation" in trace_types
        assert "daily_mission_generation" in trace_types
        assert "reward_chest_resolution" in trace_types
        assert "lifecycle_decision" in trace_types
        assert "monetization_decision" in trace_types


def test_comeback_flow_persists_notification_reactivation_and_conversion():
    with postgres_harness() as harness:
        snapshot = run_async(run_comeback_flow(harness))

        assert snapshot.session.status == "completed"
        assert snapshot.lifecycle_state is not None
        assert snapshot.lifecycle_state.current_stage in {"at_risk", "churned", "activating"}
        assert snapshot.notification_state is not None
        assert snapshot.notification_state.last_delivery_status == "sent"
        assert len(snapshot.notification_deliveries) >= 1
        assert snapshot.daily_missions[0].status == "completed"
        assert snapshot.reward_chests[0].status == "claimed"
        assert snapshot.subscription is not None
        assert snapshot.subscription.tier == "pro"
        assert snapshot.monetization_state.paywall_acceptances >= 1
        assert snapshot.monetization_state.last_accepted_at is not None
        assert any(row.converted for row in snapshot.experiment_attributions)
        assert any(int(getattr(row, "upgrade_click_count", 0) or 0) >= 1 for row in snapshot.experiment_attributions)
        event_types = {row.event_type for row in snapshot.events}
        assert "upgrade_clicked" in event_types
        assert "subscription_upgraded" in event_types
        trace_types = {row.trace_type for row in snapshot.traces}
        assert "notification_selection" in trace_types
        assert "lifecycle_transition" in trace_types
        assert "monetization_decision" in trace_types
