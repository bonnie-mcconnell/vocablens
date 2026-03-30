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
    assert "experiment_outcome_attributions" in tables
    assert "experiment_registries" in tables
    assert "experiment_registry_audits" in tables
    assert {"user_monetization_states", "monetization_offer_events"} <= tables
    assert {"daily_missions", "reward_chests"} <= tables
    assert {"user_lifecycle_states", "lifecycle_transitions"} <= tables
    assert {"user_notification_states", "notification_suppression_events"} <= tables
    assert {"notification_policy_registries", "notification_policy_audits"} <= tables
    assert "notification_policy_health_states" in tables
    assert "experiment_health_states" in tables
    assert "monetization_health_states" in tables
    assert "lifecycle_health_states" in tables
    assert "daily_loop_health_states" in tables
    assert "session_health_states" in tables
    assert "learning_health_states" in tables
    assert "content_quality_checks" in tables
    assert "content_quality_health_states" in tables
    assert "exercise_templates" in tables
    assert "exercise_template_audits" in tables
    assert "exercise_template_health_states" in tables
    assert "user_core_state" in tables
    assert "mutation_ledger" in tables
    assert "outbox_events" in tables
    assert "user_mutation_queue" in tables
    assert "learning_state_cursors" in tables
    assert "user_queue_seq" in tables
    assert "user_queue_progress" in tables
    assert "user_execution_mode" in tables
    assert "user_command_receipts" in tables
    assert "learning_worker_failures" in tables

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

    outbox_columns = {col["name"] for col in inspector.get_columns("outbox_events")}
    assert {"retry_count", "next_attempt_at", "published_at", "dead_lettered_at"} <= outbox_columns

    queue_seq_columns = {col["name"] for col in inspector.get_columns("user_queue_seq")}
    assert {"user_id", "next_seq", "updated_at"} <= queue_seq_columns
    assert "last_applied_seq" not in queue_seq_columns

    queue_progress_columns = {col["name"] for col in inspector.get_columns("user_queue_progress")}
    assert {"user_id", "last_applied_seq", "updated_at"} <= queue_progress_columns

    command_receipt_columns = {col["name"] for col in inspector.get_columns("user_command_receipts")}
    assert {"user_id", "command_id", "command_seq", "mode", "created_at"} <= command_receipt_columns

    learning_failure_columns = {col["name"] for col in inspector.get_columns("learning_worker_failures")}
    assert {"user_id", "failure_count", "quarantined_until", "last_error", "updated_at"} <= learning_failure_columns

    notification_indexes = {idx["name"] for idx in inspector.get_indexes("notification_deliveries")}
    assert "idx_notification_delivery_user" in notification_indexes
    assert "idx_notification_delivery_status" in notification_indexes
    assert "idx_notification_delivery_policy" in notification_indexes
    notification_columns = {col["name"] for col in inspector.get_columns("notification_deliveries")}
    assert {
        "policy_key",
        "policy_version",
        "source_context",
        "reference_id",
    } <= notification_columns

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

    experiment_outcome_indexes = {idx["name"] for idx in inspector.get_indexes("experiment_outcome_attributions")}
    assert "idx_experiment_outcome_attributions_variant" in experiment_outcome_indexes
    assert "idx_experiment_outcome_attributions_window_end" in experiment_outcome_indexes
    assert "idx_experiment_outcome_attributions_conversion" in experiment_outcome_indexes

    experiment_outcome_columns = {col["name"] for col in inspector.get_columns("experiment_outcome_attributions")}
    assert {
        "user_id",
        "experiment_key",
        "variant",
        "assignment_reason",
        "attribution_version",
        "exposed_at",
        "window_end_at",
        "retained_d1",
        "retained_d7",
        "converted",
        "first_conversion_at",
        "session_count",
        "message_count",
        "learning_action_count",
        "upgrade_click_count",
        "last_event_at",
        "created_at",
        "updated_at",
    } <= experiment_outcome_columns

    experiment_outcome_fks = inspector.get_foreign_keys("experiment_outcome_attributions")
    assert any(fk["referred_table"] == "users" for fk in experiment_outcome_fks)

    experiment_registry_indexes = {idx["name"] for idx in inspector.get_indexes("experiment_registries")}
    assert "idx_experiment_registries_status" in experiment_registry_indexes
    assert "idx_experiment_registries_updated_at" in experiment_registry_indexes

    experiment_registry_columns = {col["name"] for col in inspector.get_columns("experiment_registries")}
    assert {
        "experiment_key",
        "status",
        "rollout_percentage",
        "holdout_percentage",
        "is_killed",
        "baseline_variant",
        "description",
        "variants",
        "eligibility",
        "mutually_exclusive_with",
        "prerequisite_experiments",
        "created_at",
        "updated_at",
    } <= experiment_registry_columns

    experiment_registry_audit_indexes = {idx["name"] for idx in inspector.get_indexes("experiment_registry_audits")}
    assert "idx_experiment_registry_audits_experiment" in experiment_registry_audit_indexes
    assert "idx_experiment_registry_audits_action" in experiment_registry_audit_indexes

    experiment_registry_audit_columns = {col["name"] for col in inspector.get_columns("experiment_registry_audits")}
    assert {
        "id",
        "experiment_key",
        "action",
        "changed_by",
        "change_note",
        "previous_config",
        "new_config",
        "created_at",
    } <= experiment_registry_audit_columns

    experiment_registry_audit_fks = inspector.get_foreign_keys("experiment_registry_audits")
    assert any(fk["referred_table"] == "experiment_registries" for fk in experiment_registry_audit_fks)

    monetization_state_indexes = {idx["name"] for idx in inspector.get_indexes("user_monetization_states")}
    assert "idx_user_monetization_states_user" in monetization_state_indexes
    assert "idx_user_monetization_states_updated_at" in monetization_state_indexes
    assert "idx_user_monetization_states_cooldown_until" in monetization_state_indexes
    monetization_state_columns = {col["name"] for col in inspector.get_columns("user_monetization_states")}
    assert {
        "user_id",
        "current_offer_type",
        "last_paywall_type",
        "paywall_impressions",
        "paywall_dismissals",
        "paywall_acceptances",
        "paywall_skips",
        "fatigue_score",
        "cooldown_until",
        "trial_eligible",
        "conversion_propensity",
        "last_pricing",
        "last_trigger",
        "last_value_display",
        "updated_at",
    } <= monetization_state_columns
    monetization_state_fks = inspector.get_foreign_keys("user_monetization_states")
    assert any(fk["referred_table"] == "users" for fk in monetization_state_fks)

    monetization_event_indexes = {idx["name"] for idx in inspector.get_indexes("monetization_offer_events")}
    assert "idx_monetization_offer_events_user" in monetization_event_indexes
    assert "idx_monetization_offer_events_type" in monetization_event_indexes
    assert "idx_monetization_offer_events_offer" in monetization_event_indexes
    monetization_event_columns = {col["name"] for col in inspector.get_columns("monetization_offer_events")}
    assert {
        "user_id",
        "event_type",
        "offer_type",
        "paywall_type",
        "strategy",
        "geography",
        "payload",
        "created_at",
    } <= monetization_event_columns
    monetization_event_fks = inspector.get_foreign_keys("monetization_offer_events")
    assert any(fk["referred_table"] == "users" for fk in monetization_event_fks)

    daily_mission_indexes = {idx["name"] for idx in inspector.get_indexes("daily_missions")}
    assert "idx_daily_missions_user_date" in daily_mission_indexes
    assert "idx_daily_missions_status" in daily_mission_indexes
    daily_mission_columns = {col["name"] for col in inspector.get_columns("daily_missions")}
    assert {
        "user_id",
        "mission_date",
        "status",
        "weak_area",
        "mission_max_sessions",
        "steps",
        "loss_aversion_message",
        "streak_at_issue",
        "momentum_score",
        "notification_preview",
        "completed_at",
        "created_at",
        "updated_at",
    } <= daily_mission_columns
    daily_mission_fks = inspector.get_foreign_keys("daily_missions")
    assert any(fk["referred_table"] == "users" for fk in daily_mission_fks)

    reward_chest_indexes = {idx["name"] for idx in inspector.get_indexes("reward_chests")}
    assert "idx_reward_chests_user_status" in reward_chest_indexes
    assert "idx_reward_chests_created_at" in reward_chest_indexes
    reward_chest_columns = {col["name"] for col in inspector.get_columns("reward_chests")}
    assert {
        "user_id",
        "mission_id",
        "status",
        "xp_reward",
        "badge_hint",
        "payload",
        "unlocked_at",
        "claimed_at",
        "created_at",
        "updated_at",
    } <= reward_chest_columns
    reward_chest_fks = inspector.get_foreign_keys("reward_chests")
    assert any(fk["referred_table"] == "users" for fk in reward_chest_fks)
    assert any(fk["referred_table"] == "daily_missions" for fk in reward_chest_fks)

    lifecycle_state_indexes = {idx["name"] for idx in inspector.get_indexes("user_lifecycle_states")}
    assert "idx_user_lifecycle_states_user" in lifecycle_state_indexes
    assert "idx_user_lifecycle_states_stage" in lifecycle_state_indexes
    assert "idx_user_lifecycle_states_entered_at" in lifecycle_state_indexes
    lifecycle_state_columns = {col["name"] for col in inspector.get_columns("user_lifecycle_states")}
    assert {
        "user_id",
        "current_stage",
        "previous_stage",
        "current_reasons",
        "entered_at",
        "last_transition_at",
        "last_transition_source",
        "last_transition_reference_id",
        "transition_count",
        "updated_at",
    } <= lifecycle_state_columns
    lifecycle_state_fks = inspector.get_foreign_keys("user_lifecycle_states")
    assert any(fk["referred_table"] == "users" for fk in lifecycle_state_fks)

    lifecycle_transition_indexes = {idx["name"] for idx in inspector.get_indexes("lifecycle_transitions")}
    assert "idx_lifecycle_transitions_user_created" in lifecycle_transition_indexes
    assert "idx_lifecycle_transitions_to_stage" in lifecycle_transition_indexes
    lifecycle_transition_columns = {col["name"] for col in inspector.get_columns("lifecycle_transitions")}
    assert {
        "user_id",
        "from_stage",
        "to_stage",
        "reasons",
        "source",
        "reference_id",
        "payload",
        "created_at",
    } <= lifecycle_transition_columns
    lifecycle_transition_fks = inspector.get_foreign_keys("lifecycle_transitions")
    assert any(fk["referred_table"] == "users" for fk in lifecycle_transition_fks)

    notification_state_indexes = {idx["name"] for idx in inspector.get_indexes("user_notification_states")}
    assert "idx_user_notification_states_user" in notification_state_indexes
    assert "idx_user_notification_states_updated_at" in notification_state_indexes
    assert "idx_user_notification_states_cooldown_until" in notification_state_indexes
    assert "idx_user_notification_states_suppressed_until" in notification_state_indexes
    assert "idx_user_notification_states_lifecycle_stage" in notification_state_indexes
    notification_state_columns = {col["name"] for col in inspector.get_columns("user_notification_states")}
    assert {
        "user_id",
        "preferred_channel",
        "preferred_time_of_day",
        "frequency_limit",
        "lifecycle_stage",
        "lifecycle_policy_version",
        "lifecycle_policy",
        "suppression_reason",
        "suppressed_until",
        "cooldown_until",
        "sent_count_day",
        "sent_count_today",
        "last_sent_at",
        "last_delivery_channel",
        "last_delivery_status",
        "last_delivery_category",
        "last_reference_id",
        "last_decision_at",
        "last_decision_reason",
        "updated_at",
    } <= notification_state_columns
    notification_state_fks = inspector.get_foreign_keys("user_notification_states")
    assert any(fk["referred_table"] == "users" for fk in notification_state_fks)

    suppression_indexes = {idx["name"] for idx in inspector.get_indexes("notification_suppression_events")}
    assert "idx_notification_suppression_events_user" in suppression_indexes
    assert "idx_notification_suppression_events_source" in suppression_indexes
    assert "idx_notification_suppression_events_stage" in suppression_indexes
    assert "idx_notification_suppression_events_policy" in suppression_indexes
    suppression_columns = {col["name"] for col in inspector.get_columns("notification_suppression_events")}
    assert {
        "user_id",
        "event_type",
        "source",
        "reference_id",
        "policy_key",
        "policy_version",
        "lifecycle_stage",
        "suppression_reason",
        "suppressed_until",
        "payload",
        "created_at",
    } <= suppression_columns
    suppression_fks = inspector.get_foreign_keys("notification_suppression_events")
    assert any(fk["referred_table"] == "users" for fk in suppression_fks)

    notification_policy_indexes = {idx["name"] for idx in inspector.get_indexes("notification_policy_registries")}
    assert "idx_notification_policy_registries_status" in notification_policy_indexes
    assert "idx_notification_policy_registries_updated_at" in notification_policy_indexes
    notification_policy_columns = {col["name"] for col in inspector.get_columns("notification_policy_registries")}
    assert {
        "policy_key",
        "status",
        "is_killed",
        "description",
        "policy",
        "created_at",
        "updated_at",
    } <= notification_policy_columns

    notification_policy_audit_indexes = {idx["name"] for idx in inspector.get_indexes("notification_policy_audits")}
    assert "idx_notification_policy_audits_policy" in notification_policy_audit_indexes
    assert "idx_notification_policy_audits_action" in notification_policy_audit_indexes
    notification_policy_audit_columns = {col["name"] for col in inspector.get_columns("notification_policy_audits")}
    assert {
        "id",
        "policy_key",
        "action",
        "changed_by",
        "change_note",
        "previous_config",
        "new_config",
        "created_at",
    } <= notification_policy_audit_columns
    notification_policy_audit_fks = inspector.get_foreign_keys("notification_policy_audits")
    assert any(fk["referred_table"] == "notification_policy_registries" for fk in notification_policy_audit_fks)

    notification_policy_health_indexes = {idx["name"] for idx in inspector.get_indexes("notification_policy_health_states")}
    assert "idx_notification_policy_health_states_status" in notification_policy_health_indexes
    notification_policy_health_columns = {col["name"] for col in inspector.get_columns("notification_policy_health_states")}
    assert {
        "policy_key",
        "current_status",
        "latest_alert_codes",
        "metrics",
        "last_evaluated_at",
    } <= notification_policy_health_columns
    notification_policy_health_fks = inspector.get_foreign_keys("notification_policy_health_states")
    assert any(fk["referred_table"] == "notification_policy_registries" for fk in notification_policy_health_fks)

    experiment_health_indexes = {idx["name"] for idx in inspector.get_indexes("experiment_health_states")}
    assert "idx_experiment_health_states_status" in experiment_health_indexes
    experiment_health_columns = {col["name"] for col in inspector.get_columns("experiment_health_states")}
    assert {
        "experiment_key",
        "current_status",
        "latest_alert_codes",
        "metrics",
        "last_evaluated_at",
    } <= experiment_health_columns
    experiment_health_fks = inspector.get_foreign_keys("experiment_health_states")
    assert any(fk["referred_table"] == "experiment_registries" for fk in experiment_health_fks)

    monetization_health_indexes = {idx["name"] for idx in inspector.get_indexes("monetization_health_states")}
    assert "idx_monetization_health_states_status" in monetization_health_indexes
    monetization_health_columns = {col["name"] for col in inspector.get_columns("monetization_health_states")}
    assert {
        "scope_key",
        "current_status",
        "latest_alert_codes",
        "metrics",
        "last_evaluated_at",
    } <= monetization_health_columns

    lifecycle_health_indexes = {idx["name"] for idx in inspector.get_indexes("lifecycle_health_states")}
    assert "idx_lifecycle_health_states_status" in lifecycle_health_indexes
    lifecycle_health_columns = {col["name"] for col in inspector.get_columns("lifecycle_health_states")}
    assert {
        "scope_key",
        "current_status",
        "latest_alert_codes",
        "metrics",
        "last_evaluated_at",
    } <= lifecycle_health_columns

    daily_loop_health_indexes = {idx["name"] for idx in inspector.get_indexes("daily_loop_health_states")}
    assert "idx_daily_loop_health_states_status" in daily_loop_health_indexes
    daily_loop_health_columns = {col["name"] for col in inspector.get_columns("daily_loop_health_states")}
    assert {
        "scope_key",
        "current_status",
        "latest_alert_codes",
        "metrics",
        "last_evaluated_at",
    } <= daily_loop_health_columns

    session_health_indexes = {idx["name"] for idx in inspector.get_indexes("session_health_states")}
    assert "idx_session_health_states_status" in session_health_indexes
    session_health_columns = {col["name"] for col in inspector.get_columns("session_health_states")}
    assert {
        "scope_key",
        "current_status",
        "latest_alert_codes",
        "metrics",
        "last_evaluated_at",
    } <= session_health_columns

    learning_health_indexes = {idx["name"] for idx in inspector.get_indexes("learning_health_states")}
    assert "idx_learning_health_states_status" in learning_health_indexes
    learning_health_columns = {col["name"] for col in inspector.get_columns("learning_health_states")}
    assert {
        "scope_key",
        "current_status",
        "latest_alert_codes",
        "metrics",
        "last_evaluated_at",
    } <= learning_health_columns

    content_quality_check_indexes = {idx["name"] for idx in inspector.get_indexes("content_quality_checks")}
    assert "idx_content_quality_checks_source_checked" in content_quality_check_indexes
    assert "idx_content_quality_checks_status_checked" in content_quality_check_indexes
    assert "idx_content_quality_checks_reference" in content_quality_check_indexes
    content_quality_check_columns = {col["name"] for col in inspector.get_columns("content_quality_checks")}
    assert {
        "id",
        "user_id",
        "source",
        "artifact_type",
        "reference_id",
        "status",
        "score",
        "violations",
        "artifact_summary",
        "checked_at",
    } <= content_quality_check_columns
    content_quality_check_fks = inspector.get_foreign_keys("content_quality_checks")
    assert any(fk["referred_table"] == "users" for fk in content_quality_check_fks)

    content_quality_health_indexes = {idx["name"] for idx in inspector.get_indexes("content_quality_health_states")}
    assert "idx_content_quality_health_states_status" in content_quality_health_indexes
    content_quality_health_columns = {col["name"] for col in inspector.get_columns("content_quality_health_states")}
    assert {
        "scope_key",
        "current_status",
        "latest_alert_codes",
        "metrics",
        "last_evaluated_at",
    } <= content_quality_health_columns

    exercise_template_indexes = {idx["name"] for idx in inspector.get_indexes("exercise_templates")}
    assert "idx_exercise_templates_status" in exercise_template_indexes
    assert "idx_exercise_templates_type" in exercise_template_indexes
    exercise_template_columns = {col["name"] for col in inspector.get_columns("exercise_templates")}
    assert {
        "id",
        "template_key",
        "exercise_type",
        "objective",
        "difficulty",
        "status",
        "prompt_template",
        "answer_source",
        "choice_count",
        "metadata",
        "created_at",
        "updated_at",
    } <= exercise_template_columns

    exercise_template_audit_indexes = {idx["name"] for idx in inspector.get_indexes("exercise_template_audits")}
    assert "idx_exercise_template_audits_template" in exercise_template_audit_indexes
    assert "idx_exercise_template_audits_action" in exercise_template_audit_indexes
    exercise_template_audit_columns = {col["name"] for col in inspector.get_columns("exercise_template_audits")}
    assert {
        "id",
        "template_key",
        "action",
        "changed_by",
        "change_note",
        "previous_config",
        "new_config",
        "fixture_report",
        "created_at",
    } <= exercise_template_audit_columns

    exercise_template_health_indexes = {idx["name"] for idx in inspector.get_indexes("exercise_template_health_states")}
    assert "idx_exercise_template_health_states_status" in exercise_template_health_indexes
    exercise_template_health_columns = {col["name"] for col in inspector.get_columns("exercise_template_health_states")}
    assert {
        "scope_key",
        "current_status",
        "latest_alert_codes",
        "metrics",
        "last_evaluated_at",
    } <= exercise_template_health_columns

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
        "contract_version",
        "duration_seconds",
        "mode",
        "weak_area",
        "max_response_words",
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
        "submission_id",
        "learner_response",
        "response_word_count",
        "response_char_count",
        "is_correct",
        "improvement_score",
        "validation_payload",
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
    assert "experiment_outcome_attributions" not in tables
    assert "experiment_registries" not in tables
    assert "experiment_registry_audits" not in tables
    assert "user_monetization_states" not in tables
    assert "monetization_offer_events" not in tables
    assert "daily_missions" not in tables
    assert "reward_chests" not in tables
    assert "user_lifecycle_states" not in tables
    assert "lifecycle_transitions" not in tables
    assert "user_notification_states" not in tables
    assert "notification_suppression_events" not in tables
    assert "notification_policy_registries" not in tables
    assert "notification_policy_audits" not in tables
    assert "notification_policy_health_states" not in tables
    assert "experiment_health_states" not in tables
    assert "monetization_health_states" not in tables
    assert "lifecycle_health_states" not in tables
    assert "daily_loop_health_states" not in tables
    assert "session_health_states" not in tables
    assert "learning_health_states" not in tables
    assert "content_quality_checks" not in tables
    assert "content_quality_health_states" not in tables
    assert "exercise_templates" not in tables
    assert "exercise_template_audits" not in tables
    assert "exercise_template_health_states" not in tables

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
    assert "experiment_outcome_attributions" in tables
    assert "experiment_registries" in tables
    assert "experiment_registry_audits" in tables
    assert {"user_monetization_states", "monetization_offer_events"} <= tables
    assert {"daily_missions", "reward_chests"} <= tables
    assert {"user_lifecycle_states", "lifecycle_transitions"} <= tables
    assert {"user_notification_states", "notification_suppression_events"} <= tables
    assert {"notification_policy_registries", "notification_policy_audits"} <= tables
    assert "notification_policy_health_states" in tables
    assert "experiment_health_states" in tables
    assert "monetization_health_states" in tables
    assert "lifecycle_health_states" in tables
    assert "daily_loop_health_states" in tables
    assert "session_health_states" in tables
    assert "learning_health_states" in tables
    assert "content_quality_checks" in tables
    assert "content_quality_health_states" in tables
    assert "exercise_templates" in tables
    assert "exercise_template_audits" in tables
    assert "exercise_template_health_states" in tables
    engine.dispose()

    shutil.rmtree(ARTIFACTS, ignore_errors=True)
