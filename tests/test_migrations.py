from pathlib import Path
import shutil

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".migration_test_artifacts"


def _make_config(db_path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def test_upgrade_downgrade_upgrade_round_trip():
    if ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS, ignore_errors=True)
    ARTIFACTS.mkdir(exist_ok=True)
    db_path = ARTIFACTS / "migrations.sqlite"
    config = _make_config(db_path)

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    assert {"usage_logs", "subscriptions", "mistake_patterns", "user_profiles"} <= tables
    assert "knowledge_graph_edges" in tables
    assert {"notification_deliveries", "subscription_events"} <= tables
    assert "experiment_assignments" in tables
    assert "events" in tables
    assert "vocabulary" in tables
    assert {"user_learning_states", "user_engagement_states", "user_progress_states"} <= tables
    assert "onboarding_flow_states" in tables
    assert {"learning_sessions", "learning_session_attempts"} <= tables
    assert "decision_traces" in tables
    assert "experiment_exposures" in tables

    usage_indexes = {idx["name"] for idx in inspector.get_indexes("usage_logs")}
    assert "idx_usage_user_day" in usage_indexes
    assert "idx_usage_endpoint" in usage_indexes

    subscription_indexes = {idx["name"] for idx in inspector.get_indexes("subscriptions")}
    assert "idx_subscription_user" in subscription_indexes
    assert "idx_subscription_renewed_at" in subscription_indexes
    subscription_columns = {col["name"] for col in inspector.get_columns("subscriptions")}
    assert {"trial_started_at", "trial_ends_at", "trial_tier"} <= subscription_columns

    mistake_indexes = {idx["name"] for idx in inspector.get_indexes("mistake_patterns")}
    assert "idx_mistake_user_category" in mistake_indexes
    assert "idx_mistake_user_last_seen" in mistake_indexes

    profile_indexes = {idx["name"] for idx in inspector.get_indexes("user_profiles")}
    assert "idx_user_profile_user" in profile_indexes
    assert "idx_user_profile_updated_at" in profile_indexes
    assert "idx_user_profile_last_active_at" in profile_indexes
    assert "idx_user_profile_drop_off_risk" in profile_indexes

    profile_columns = {col["name"] for col in inspector.get_columns("user_profiles")}
    assert {
        "last_active_at",
        "session_frequency",
        "current_streak",
        "longest_streak",
        "drop_off_risk",
        "preferred_channel",
        "preferred_time_of_day",
        "frequency_limit",
    } <= profile_columns

    fks = inspector.get_foreign_keys("usage_logs")
    assert any(fk["referred_table"] == "users" for fk in fks)
    fks = inspector.get_foreign_keys("subscriptions")
    assert any(fk["referred_table"] == "users" for fk in fks)
    fks = inspector.get_foreign_keys("mistake_patterns")
    assert any(fk["referred_table"] == "users" for fk in fks)
    fks = inspector.get_foreign_keys("user_profiles")
    assert any(fk["referred_table"] == "users" for fk in fks)
    kge_fks = inspector.get_foreign_keys("knowledge_graph_edges")
    assert any(fk["referred_table"] == "users" for fk in kge_fks)
    notification_fks = inspector.get_foreign_keys("notification_deliveries")
    assert any(fk["referred_table"] == "users" for fk in notification_fks)
    subscription_event_fks = inspector.get_foreign_keys("subscription_events")
    assert any(fk["referred_table"] == "users" for fk in subscription_event_fks)

    kge_columns = {col["name"] for col in inspector.get_columns("knowledge_graph_edges")}
    assert "user_id" in kge_columns
    kge_indexes = {idx["name"] for idx in inspector.get_indexes("knowledge_graph_edges")}
    assert "idx_kge_user_relation" in kge_indexes
    assert "idx_kge_user_target" in kge_indexes
    assert "idx_kge_user_source" in kge_indexes

    notification_indexes = {idx["name"] for idx in inspector.get_indexes("notification_deliveries")}
    assert "idx_notification_delivery_user" in notification_indexes
    assert "idx_notification_delivery_status" in notification_indexes

    subscription_event_indexes = {idx["name"] for idx in inspector.get_indexes("subscription_events")}
    assert "idx_subscription_events_user" in subscription_event_indexes
    assert "idx_subscription_events_type" in subscription_event_indexes

    experiment_indexes = {idx["name"] for idx in inspector.get_indexes("experiment_assignments")}
    assert "idx_experiment_assignments_variant" in experiment_indexes
    assert "idx_experiment_assignments_assigned_at" in experiment_indexes

    experiment_columns = {col["name"] for col in inspector.get_columns("experiment_assignments")}
    assert {"user_id", "experiment_key", "variant", "assigned_at"} <= experiment_columns

    experiment_fks = inspector.get_foreign_keys("experiment_assignments")
    assert any(fk["referred_table"] == "users" for fk in experiment_fks)

    experiment_exposure_indexes = {idx["name"] for idx in inspector.get_indexes("experiment_exposures")}
    assert "idx_experiment_exposures_variant" in experiment_exposure_indexes
    assert "idx_experiment_exposures_exposed_at" in experiment_exposure_indexes

    experiment_exposure_columns = {col["name"] for col in inspector.get_columns("experiment_exposures")}
    assert {"user_id", "experiment_key", "variant", "exposed_at"} <= experiment_exposure_columns

    experiment_exposure_fks = inspector.get_foreign_keys("experiment_exposures")
    assert any(fk["referred_table"] == "users" for fk in experiment_exposure_fks)

    event_indexes = {idx["name"] for idx in inspector.get_indexes("events")}
    assert "idx_events_user" in event_indexes
    assert "idx_events_type" in event_indexes

    event_columns = {col["name"] for col in inspector.get_columns("events")}
    assert {"id", "user_id", "event_type", "payload", "created_at"} <= event_columns

    event_fks = inspector.get_foreign_keys("events")
    assert any(fk["referred_table"] == "users" for fk in event_fks)

    vocabulary_columns = {col["name"] for col in inspector.get_columns("vocabulary")}
    assert {"last_seen_at", "success_rate", "decay_score"} <= vocabulary_columns
    vocabulary_indexes = {idx["name"] for idx in inspector.get_indexes("vocabulary")}
    assert "idx_vocab_user_decay" in vocabulary_indexes

    learning_state_columns = {col["name"] for col in inspector.get_columns("user_learning_states")}
    assert {
        "user_id",
        "skills",
        "weak_areas",
        "mastery_percent",
        "accuracy_rate",
        "response_speed_seconds",
        "updated_at",
    } <= learning_state_columns
    learning_state_indexes = {idx["name"] for idx in inspector.get_indexes("user_learning_states")}
    assert "idx_user_learning_states_user" in learning_state_indexes
    assert "idx_user_learning_states_updated_at" in learning_state_indexes
    learning_state_fks = inspector.get_foreign_keys("user_learning_states")
    assert any(fk["referred_table"] == "users" for fk in learning_state_fks)

    engagement_state_columns = {col["name"] for col in inspector.get_columns("user_engagement_states")}
    assert {
        "user_id",
        "current_streak",
        "longest_streak",
        "momentum_score",
        "total_sessions",
        "sessions_last_3_days",
        "last_session_at",
        "shields_used_this_week",
        "daily_mission_completed_at",
        "interaction_stats",
        "updated_at",
    } <= engagement_state_columns
    engagement_state_indexes = {idx["name"] for idx in inspector.get_indexes("user_engagement_states")}
    assert "idx_user_engagement_states_user" in engagement_state_indexes
    assert "idx_user_engagement_states_updated_at" in engagement_state_indexes
    engagement_state_fks = inspector.get_foreign_keys("user_engagement_states")
    assert any(fk["referred_table"] == "users" for fk in engagement_state_fks)

    progress_state_columns = {col["name"] for col in inspector.get_columns("user_progress_states")}
    assert {"user_id", "xp", "level", "milestones", "updated_at"} <= progress_state_columns
    progress_state_indexes = {idx["name"] for idx in inspector.get_indexes("user_progress_states")}
    assert "idx_user_progress_states_user" in progress_state_indexes
    assert "idx_user_progress_states_updated_at" in progress_state_indexes
    progress_state_fks = inspector.get_foreign_keys("user_progress_states")
    assert any(fk["referred_table"] == "users" for fk in progress_state_fks)

    onboarding_state_columns = {col["name"] for col in inspector.get_columns("onboarding_flow_states")}
    assert {
        "user_id",
        "current_step",
        "steps_completed",
        "identity",
        "personalization",
        "wow",
        "early_success_score",
        "progress_illusion",
        "paywall",
        "habit_lock_in",
        "created_at",
        "updated_at",
    } <= onboarding_state_columns
    onboarding_state_indexes = {idx["name"] for idx in inspector.get_indexes("onboarding_flow_states")}
    assert "idx_onboarding_flow_states_user" in onboarding_state_indexes
    assert "idx_onboarding_flow_states_step" in onboarding_state_indexes
    assert "idx_onboarding_flow_states_updated_at" in onboarding_state_indexes
    onboarding_state_fks = inspector.get_foreign_keys("onboarding_flow_states")
    assert any(fk["referred_table"] == "users" for fk in onboarding_state_fks)

    learning_session_columns = {col["name"] for col in inspector.get_columns("learning_sessions")}
    assert {
        "session_id",
        "user_id",
        "status",
        "duration_seconds",
        "mode",
        "weak_area",
        "session_payload",
        "expires_at",
        "evaluation_count",
    } <= learning_session_columns
    learning_session_indexes = {idx["name"] for idx in inspector.get_indexes("learning_sessions")}
    assert "idx_learning_sessions_user_status" in learning_session_indexes
    assert "idx_learning_sessions_user_created" in learning_session_indexes
    assert "idx_learning_sessions_expires_at" in learning_session_indexes
    learning_session_fks = inspector.get_foreign_keys("learning_sessions")
    assert any(fk["referred_table"] == "users" for fk in learning_session_fks)

    learning_attempt_columns = {col["name"] for col in inspector.get_columns("learning_session_attempts")}
    assert {
        "id",
        "session_id",
        "user_id",
        "learner_response",
        "is_correct",
        "improvement_score",
        "feedback_payload",
        "created_at",
    } <= learning_attempt_columns
    learning_attempt_indexes = {idx["name"] for idx in inspector.get_indexes("learning_session_attempts")}
    assert "idx_learning_session_attempts_session" in learning_attempt_indexes
    assert "idx_learning_session_attempts_user" in learning_attempt_indexes
    learning_attempt_fks = inspector.get_foreign_keys("learning_session_attempts")
    assert any(fk["referred_table"] == "learning_sessions" for fk in learning_attempt_fks)
    assert any(fk["referred_table"] == "users" for fk in learning_attempt_fks)

    decision_trace_columns = {col["name"] for col in inspector.get_columns("decision_traces")}
    assert {
        "id",
        "user_id",
        "trace_type",
        "source",
        "reference_id",
        "policy_version",
        "inputs",
        "outputs",
        "reason",
        "created_at",
    } <= decision_trace_columns
    decision_trace_indexes = {idx["name"] for idx in inspector.get_indexes("decision_traces")}
    assert "idx_decision_traces_user_type" in decision_trace_indexes
    assert "idx_decision_traces_reference" in decision_trace_indexes
    decision_trace_fks = inspector.get_foreign_keys("decision_traces")
    assert any(fk["referred_table"] == "users" for fk in decision_trace_fks)

    command.downgrade(config, "20260317_0001")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "usage_logs" not in tables
    assert "subscriptions" not in tables
    assert "mistake_patterns" not in tables
    assert "user_profiles" not in tables
    assert "notification_deliveries" not in tables
    assert "subscription_events" not in tables
    assert "experiment_assignments" not in tables
    assert "events" not in tables
    assert "user_learning_states" not in tables
    assert "user_engagement_states" not in tables
    assert "user_progress_states" not in tables
    assert "onboarding_flow_states" not in tables
    assert "learning_sessions" not in tables
    assert "learning_session_attempts" not in tables
    assert "decision_traces" not in tables
    assert "experiment_exposures" not in tables

    command.upgrade(config, "head")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"usage_logs", "subscriptions", "mistake_patterns", "user_profiles"} <= tables
    assert {"notification_deliveries", "subscription_events"} <= tables
    assert "experiment_assignments" in tables
    assert "events" in tables
    assert {"user_learning_states", "user_engagement_states", "user_progress_states"} <= tables
    assert "onboarding_flow_states" in tables
    assert {"learning_sessions", "learning_session_attempts"} <= tables
    assert "decision_traces" in tables
    assert "experiment_exposures" in tables
    engine.dispose()

    shutil.rmtree(ARTIFACTS, ignore_errors=True)
