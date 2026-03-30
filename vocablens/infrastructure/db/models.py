from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    PrimaryKeyConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from vocablens.core.time import utc_now

Base = declarative_base()


class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    vocabulary = relationship("VocabularyORM", back_populates="user")


class VocabularyORM(Base):
    __tablename__ = "vocabulary"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    source_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=False)
    source_lang = Column(String, nullable=False)
    target_lang = Column(String, nullable=False)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_reviewed_at = Column(DateTime)
    last_seen_at = Column(DateTime)
    review_count = Column(Integer, default=0, nullable=False)
    ease_factor = Column(Float, default=2.5, nullable=False)
    interval = Column(Integer, default=1, nullable=False)
    repetitions = Column(Integer, default=0, nullable=False)
    next_review_due = Column(DateTime)
    success_rate = Column(Float, default=0.0, nullable=False)
    decay_score = Column(Float, default=0.0, nullable=False)

    example_source_sentence = Column(Text)
    example_translated_sentence = Column(Text)
    grammar_note = Column(Text)
    semantic_cluster = Column(Text)

    user = relationship("UserORM", back_populates="vocabulary")


Index("idx_vocab_user_id", VocabularyORM.user_id)
Index("idx_vocab_next_due", VocabularyORM.next_review_due)
Index("idx_vocab_cluster", VocabularyORM.semantic_cluster)
Index("idx_vocab_user_decay", VocabularyORM.user_id, VocabularyORM.decay_score)


class TranslationCacheORM(Base):
    __tablename__ = "translation_cache"

    text = Column(Text, primary_key=True)
    source_lang = Column(String, primary_key=True)
    target_lang = Column(String, primary_key=True)
    translation = Column(Text, nullable=False)


Index(
    "idx_translation_cache_langs",
    TranslationCacheORM.source_lang,
    TranslationCacheORM.target_lang,
)


class ConversationHistoryORM(Base):
    __tablename__ = "conversation_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


Index("idx_conversation_history_user", ConversationHistoryORM.user_id, ConversationHistoryORM.created_at)


class SkillTrackingORM(Base):
    __tablename__ = "skill_tracking"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    skill = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


Index("idx_skill_tracking_user", SkillTrackingORM.user_id, SkillTrackingORM.created_at)


class LearningEventORM(Base):
    __tablename__ = "learning_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False)
    payload_json = Column(Text)
    created_at = Column(DateTime, default=utc_now, nullable=False)


Index("idx_learning_events_user", LearningEventORM.user_id, LearningEventORM.created_at)


class EventORM(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("idx_events_user", "user_id", "created_at"),
        Index("idx_events_type", "event_type", "created_at"),
    )

    id = Column(BigInteger, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class KnowledgeGraphEdgeORM(Base):
    __tablename__ = "knowledge_graph_edges"
    __table_args__ = (
        Index("idx_kge_user_relation", "user_id", "relation_type"),
        Index("idx_kge_user_target", "user_id", "target_node"),
        Index("idx_kge_user_source", "user_id", "source_node"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    source_node = Column(Text, nullable=False)
    target_node = Column(Text, nullable=False)
    relation_type = Column(String, nullable=False)
    weight = Column(Float, default=1.0)
    created_at = Column(DateTime, default=utc_now, nullable=False)


Index("idx_kge_source", KnowledgeGraphEdgeORM.source_node, KnowledgeGraphEdgeORM.relation_type)


class EmbeddingORM(Base):
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True)
    word = Column(Text, nullable=False, unique=True)
    embedding = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)


Index("idx_embeddings_word", EmbeddingORM.word)


class UsageLogORM(Base):
    __tablename__ = "usage_logs"
    __table_args__ = (
        CheckConstraint("tokens_used >= 0", name="ck_usage_logs_tokens_used_nonnegative"),
        Index("idx_usage_user_day", "user_id", "created_at"),
        Index("idx_usage_endpoint", "endpoint"),
    )

    id = Column(BigInteger, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    endpoint = Column(String, nullable=False)
    tokens_used = Column(Integer, default=0, nullable=False)
    success = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class SubscriptionORM(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_subscriptions_user_id"),
        CheckConstraint("request_limit >= 0", name="ck_subscriptions_request_limit_nonnegative"),
        CheckConstraint("token_limit >= 0", name="ck_subscriptions_token_limit_nonnegative"),
        Index("idx_subscription_user", "user_id"),
        Index("idx_subscription_renewed_at", "renewed_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    tier = Column(String, default="free", nullable=False)
    request_limit = Column(Integer, default=100, nullable=False)
    token_limit = Column(Integer, default=50000, nullable=False)
    renewed_at = Column(DateTime, default=utc_now, nullable=False)
    trial_started_at = Column(DateTime)
    trial_ends_at = Column(DateTime)
    trial_tier = Column(String)
    created_at = Column(DateTime, default=utc_now, nullable=False)

class MistakePatternORM(Base):
    __tablename__ = "mistake_patterns"
    __table_args__ = (
        UniqueConstraint("user_id", "category", "pattern", name="uq_mistake_patterns_user_category_pattern"),
        CheckConstraint("count >= 1", name="ck_mistake_patterns_count_positive"),
        Index("idx_mistake_user_category", "user_id", "category"),
        Index("idx_mistake_user_last_seen", "user_id", "last_seen_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category = Column(String, nullable=False)  # grammar | vocabulary | repetition
    pattern = Column(Text, nullable=False)
    count = Column(Integer, default=1, nullable=False)
    last_seen_at = Column(DateTime, default=utc_now, nullable=False)

class UserProfileORM(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
        CheckConstraint("learning_speed > 0", name="ck_user_profiles_learning_speed_positive"),
        CheckConstraint("retention_rate >= 0 AND retention_rate <= 1", name="ck_user_profiles_retention_rate_range"),
        CheckConstraint("session_frequency >= 0", name="ck_user_profiles_session_frequency_nonnegative"),
        CheckConstraint("current_streak >= 0", name="ck_user_profiles_current_streak_nonnegative"),
        CheckConstraint("longest_streak >= 0", name="ck_user_profiles_longest_streak_nonnegative"),
        CheckConstraint("drop_off_risk >= 0 AND drop_off_risk <= 1", name="ck_user_profiles_drop_off_risk_range"),
        CheckConstraint(
            "preferred_channel IN ('email', 'push', 'in_app')",
            name="ck_user_profiles_preferred_channel_valid",
        ),
        CheckConstraint("preferred_time_of_day >= 0 AND preferred_time_of_day <= 23", name="ck_user_profiles_preferred_time_of_day_range"),
        CheckConstraint("frequency_limit >= 0", name="ck_user_profiles_frequency_limit_nonnegative"),
        Index("idx_user_profile_user", "user_id"),
        Index("idx_user_profile_updated_at", "updated_at"),
        Index("idx_user_profile_last_active_at", "last_active_at"),
        Index("idx_user_profile_drop_off_risk", "drop_off_risk"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    learning_speed = Column(Float, default=1.0, nullable=False)  # relative multiplier
    retention_rate = Column(Float, default=0.8, nullable=False)  # 0-1
    difficulty_preference = Column(String, default="medium", nullable=False)  # easy|medium|hard
    content_preference = Column(String, default="mixed", nullable=False)  # vocab|grammar|conversation|mixed
    last_active_at = Column(DateTime, default=utc_now, nullable=False)
    session_frequency = Column(Float, default=0.0, nullable=False)
    current_streak = Column(Integer, default=0, nullable=False)
    longest_streak = Column(Integer, default=0, nullable=False)
    drop_off_risk = Column(Float, default=0.0, nullable=False)
    preferred_channel = Column(String, default="push", nullable=False)
    preferred_time_of_day = Column(Integer, default=18, nullable=False)
    frequency_limit = Column(Integer, default=2, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class NotificationDeliveryORM(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index("idx_notification_delivery_user", "user_id", "created_at"),
        Index("idx_notification_delivery_status", "status", "created_at"),
        Index("idx_notification_delivery_policy", "policy_key", "policy_version", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    status = Column(String, nullable=False)
    policy_key = Column(String)
    policy_version = Column(String)
    source_context = Column(String)
    reference_id = Column(String)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    payload_json = Column(Text)
    error_message = Column(Text)
    attempt_count = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class UserNotificationStateORM(Base):
    __tablename__ = "user_notification_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_notification_states_user_id"),
        CheckConstraint(
            "preferred_channel IN ('email', 'push', 'in_app')",
            name="ck_user_notification_states_preferred_channel_valid",
        ),
        CheckConstraint(
            "preferred_time_of_day >= 0 AND preferred_time_of_day <= 23",
            name="ck_user_notification_states_preferred_time_of_day_range",
        ),
        CheckConstraint(
            "frequency_limit >= 0",
            name="ck_user_notification_states_frequency_limit_nonnegative",
        ),
        CheckConstraint(
            "sent_count_today >= 0",
            name="ck_user_notification_states_sent_count_today_nonnegative",
        ),
        Index("idx_user_notification_states_user", "user_id"),
        Index("idx_user_notification_states_updated_at", "updated_at"),
        Index("idx_user_notification_states_cooldown_until", "cooldown_until"),
        Index("idx_user_notification_states_suppressed_until", "suppressed_until"),
        Index("idx_user_notification_states_lifecycle_stage", "lifecycle_stage", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    preferred_channel = Column(String, default="push", nullable=False)
    preferred_time_of_day = Column(Integer, default=18, nullable=False)
    frequency_limit = Column(Integer, default=2, nullable=False)
    lifecycle_stage = Column(String)
    lifecycle_policy_version = Column(String, nullable=False, default="v1")
    lifecycle_policy = Column(JSON, nullable=False, default=dict)
    suppression_reason = Column(Text)
    suppressed_until = Column(DateTime)
    cooldown_until = Column(DateTime)
    sent_count_day = Column(String)
    sent_count_today = Column(Integer, default=0, nullable=False)
    last_sent_at = Column(DateTime)
    last_delivery_channel = Column(String)
    last_delivery_status = Column(String)
    last_delivery_category = Column(String)
    last_reference_id = Column(String)
    last_decision_at = Column(DateTime)
    last_decision_reason = Column(Text)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class NotificationSuppressionEventORM(Base):
    __tablename__ = "notification_suppression_events"
    __table_args__ = (
        Index("idx_notification_suppression_events_user", "user_id", "created_at"),
        Index("idx_notification_suppression_events_source", "source", "created_at"),
        Index("idx_notification_suppression_events_stage", "lifecycle_stage", "created_at"),
        Index("idx_notification_suppression_events_policy", "policy_key", "policy_version", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False)
    source = Column(String, nullable=False)
    reference_id = Column(String)
    policy_key = Column(String)
    policy_version = Column(String)
    lifecycle_stage = Column(String)
    suppression_reason = Column(Text)
    suppressed_until = Column(DateTime)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class NotificationPolicyRegistryORM(Base):
    __tablename__ = "notification_policy_registries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'archived')",
            name="ck_notification_policy_registries_status_valid",
        ),
        Index("idx_notification_policy_registries_status", "status"),
        Index("idx_notification_policy_registries_updated_at", "updated_at"),
    )

    policy_key = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="draft")
    is_killed = Column(Boolean, nullable=False, default=False)
    description = Column(Text)
    policy = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class NotificationPolicyAuditORM(Base):
    __tablename__ = "notification_policy_audits"
    __table_args__ = (
        Index("idx_notification_policy_audits_policy", "policy_key", "created_at"),
        Index("idx_notification_policy_audits_action", "action", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    policy_key = Column(
        String,
        ForeignKey("notification_policy_registries.policy_key", ondelete="CASCADE"),
        nullable=False,
    )
    action = Column(String, nullable=False)
    changed_by = Column(String, nullable=False)
    change_note = Column(Text, nullable=False)
    previous_config = Column(JSON, nullable=False, default=dict)
    new_config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class ExperimentHealthStateORM(Base):
    __tablename__ = "experiment_health_states"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_experiment_health_states_status_valid",
        ),
        Index("idx_experiment_health_states_status", "current_status", "last_evaluated_at"),
    )

    experiment_key = Column(
        String,
        ForeignKey("experiment_registries.experiment_key", ondelete="CASCADE"),
        primary_key=True,
    )
    current_status = Column(String, nullable=False)
    latest_alert_codes = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=dict)
    last_evaluated_at = Column(DateTime, default=utc_now, nullable=False)


class NotificationPolicyHealthStateORM(Base):
    __tablename__ = "notification_policy_health_states"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_notification_policy_health_states_status_valid",
        ),
        Index("idx_notification_policy_health_states_status", "current_status", "last_evaluated_at"),
    )

    policy_key = Column(
        String,
        ForeignKey("notification_policy_registries.policy_key", ondelete="CASCADE"),
        primary_key=True,
    )
    current_status = Column(String, nullable=False)
    latest_alert_codes = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=dict)
    last_evaluated_at = Column(DateTime, default=utc_now, nullable=False)


class SubscriptionEventORM(Base):
    __tablename__ = "subscription_events"
    __table_args__ = (
        Index("idx_subscription_events_user", "user_id", "created_at"),
        Index("idx_subscription_events_type", "event_type", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False)
    from_tier = Column(String)
    to_tier = Column(String)
    feature_name = Column(String)
    metadata_json = Column(Text)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class ExperimentAssignmentORM(Base):
    __tablename__ = "experiment_assignments"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "experiment_key", name="pk_experiment_assignments"),
        Index("idx_experiment_assignments_variant", "experiment_key", "variant"),
        Index("idx_experiment_assignments_assigned_at", "assigned_at"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    experiment_key = Column(String, nullable=False)
    variant = Column(String, nullable=False)
    assigned_at = Column(DateTime, default=utc_now, nullable=False)


class ExperimentExposureORM(Base):
    __tablename__ = "experiment_exposures"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "experiment_key", name="pk_experiment_exposures"),
        Index("idx_experiment_exposures_variant", "experiment_key", "variant"),
        Index("idx_experiment_exposures_exposed_at", "exposed_at"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    experiment_key = Column(String, nullable=False)
    variant = Column(String, nullable=False)
    exposed_at = Column(DateTime, default=utc_now, nullable=False)


class ExperimentOutcomeAttributionORM(Base):
    __tablename__ = "experiment_outcome_attributions"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "experiment_key", name="pk_experiment_outcome_attributions"),
        CheckConstraint("session_count >= 0", name="ck_experiment_outcome_attributions_session_count_nonnegative"),
        CheckConstraint("message_count >= 0", name="ck_experiment_outcome_attributions_message_count_nonnegative"),
        CheckConstraint(
            "learning_action_count >= 0",
            name="ck_experiment_outcome_attributions_learning_action_count_nonnegative",
        ),
        CheckConstraint(
            "upgrade_click_count >= 0",
            name="ck_experiment_outcome_attributions_upgrade_click_count_nonnegative",
        ),
        Index("idx_experiment_outcome_attributions_variant", "experiment_key", "variant"),
        Index("idx_experiment_outcome_attributions_window_end", "window_end_at"),
        Index("idx_experiment_outcome_attributions_conversion", "experiment_key", "converted"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    experiment_key = Column(String, nullable=False)
    variant = Column(String, nullable=False)
    assignment_reason = Column(String, nullable=False, default="rollout")
    attribution_version = Column(String, nullable=False, default="v1")
    exposed_at = Column(DateTime, default=utc_now, nullable=False)
    window_end_at = Column(DateTime, nullable=False)
    retained_d1 = Column(Boolean, nullable=False, default=False)
    retained_d7 = Column(Boolean, nullable=False, default=False)
    converted = Column(Boolean, nullable=False, default=False)
    first_conversion_at = Column(DateTime)
    session_count = Column(Integer, nullable=False, default=0)
    message_count = Column(Integer, nullable=False, default=0)
    learning_action_count = Column(Integer, nullable=False, default=0)
    upgrade_click_count = Column(Integer, nullable=False, default=0)
    last_event_at = Column(DateTime)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class ExperimentRegistryORM(Base):
    __tablename__ = "experiment_registries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'archived')",
            name="ck_experiment_registries_status_valid",
        ),
        CheckConstraint(
            "rollout_percentage >= 0 AND rollout_percentage <= 100",
            name="ck_experiment_registries_rollout_percentage_range",
        ),
        CheckConstraint(
            "holdout_percentage >= 0 AND holdout_percentage <= 100",
            name="ck_experiment_registries_holdout_percentage_range",
        ),
        Index("idx_experiment_registries_status", "status"),
        Index("idx_experiment_registries_updated_at", "updated_at"),
    )

    experiment_key = Column(String, primary_key=True)
    status = Column(String, nullable=False, default="draft")
    rollout_percentage = Column(Integer, nullable=False, default=100)
    holdout_percentage = Column(Integer, nullable=False, default=0)
    is_killed = Column(Boolean, nullable=False, default=False)
    baseline_variant = Column(String, nullable=False, default="control")
    description = Column(Text)
    variants = Column(JSON, nullable=False, default=list)
    eligibility = Column(JSON, nullable=False, default=dict)
    mutually_exclusive_with = Column(JSON, nullable=False, default=list)
    prerequisite_experiments = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class ExperimentRegistryAuditORM(Base):
    __tablename__ = "experiment_registry_audits"
    __table_args__ = (
        Index("idx_experiment_registry_audits_experiment", "experiment_key", "created_at"),
        Index("idx_experiment_registry_audits_action", "action", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    experiment_key = Column(
        String,
        ForeignKey("experiment_registries.experiment_key", ondelete="CASCADE"),
        nullable=False,
    )
    action = Column(String, nullable=False)
    changed_by = Column(String, nullable=False)
    change_note = Column(Text, nullable=False)
    previous_config = Column(JSON, nullable=False, default=dict)
    new_config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class UserMonetizationStateORM(Base):
    __tablename__ = "user_monetization_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_monetization_states_user_id"),
        CheckConstraint("paywall_impressions >= 0", name="ck_user_monetization_states_impressions_nonnegative"),
        CheckConstraint("paywall_dismissals >= 0", name="ck_user_monetization_states_dismissals_nonnegative"),
        CheckConstraint("paywall_acceptances >= 0", name="ck_user_monetization_states_acceptances_nonnegative"),
        CheckConstraint("paywall_skips >= 0", name="ck_user_monetization_states_skips_nonnegative"),
        CheckConstraint("fatigue_score >= 0", name="ck_user_monetization_states_fatigue_nonnegative"),
        CheckConstraint(
            "conversion_propensity >= 0 AND conversion_propensity <= 1",
            name="ck_user_monetization_states_conversion_propensity_range",
        ),
        Index("idx_user_monetization_states_user", "user_id"),
        Index("idx_user_monetization_states_updated_at", "updated_at"),
        Index("idx_user_monetization_states_cooldown_until", "cooldown_until"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    current_offer_type = Column(String)
    last_paywall_type = Column(String)
    last_paywall_reason = Column(Text)
    current_strategy = Column(String)
    current_geography = Column(String)
    lifecycle_stage = Column(String)
    paywall_impressions = Column(Integer, default=0, nullable=False)
    paywall_dismissals = Column(Integer, default=0, nullable=False)
    paywall_acceptances = Column(Integer, default=0, nullable=False)
    paywall_skips = Column(Integer, default=0, nullable=False)
    fatigue_score = Column(Integer, default=0, nullable=False)
    cooldown_until = Column(DateTime)
    trial_eligible = Column(Boolean, default=True, nullable=False)
    trial_started_at = Column(DateTime)
    trial_ends_at = Column(DateTime)
    trial_offer_days = Column(Integer)
    conversion_propensity = Column(Float, default=0.0, nullable=False)
    last_offer_at = Column(DateTime)
    last_impression_at = Column(DateTime)
    last_dismissed_at = Column(DateTime)
    last_accepted_at = Column(DateTime)
    last_skipped_at = Column(DateTime)
    last_pricing = Column(JSON, nullable=False, default=dict)
    last_trigger = Column(JSON, nullable=False, default=dict)
    last_value_display = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class MonetizationHealthStateORM(Base):
    __tablename__ = "monetization_health_states"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_monetization_health_states_status_valid",
        ),
        Index("idx_monetization_health_states_status", "current_status", "last_evaluated_at"),
    )

    scope_key = Column(String, primary_key=True)
    current_status = Column(String, nullable=False)
    latest_alert_codes = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=dict)
    last_evaluated_at = Column(DateTime, default=utc_now, nullable=False)


class LifecycleHealthStateORM(Base):
    __tablename__ = "lifecycle_health_states"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_lifecycle_health_states_status_valid",
        ),
        Index("idx_lifecycle_health_states_status", "current_status", "last_evaluated_at"),
    )

    scope_key = Column(String, primary_key=True)
    current_status = Column(String, nullable=False)
    latest_alert_codes = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=dict)
    last_evaluated_at = Column(DateTime, default=utc_now, nullable=False)


class DailyLoopHealthStateORM(Base):
    __tablename__ = "daily_loop_health_states"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_daily_loop_health_states_status_valid",
        ),
        Index("idx_daily_loop_health_states_status", "current_status", "last_evaluated_at"),
    )

    scope_key = Column(String, primary_key=True)
    current_status = Column(String, nullable=False)
    latest_alert_codes = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=dict)
    last_evaluated_at = Column(DateTime, default=utc_now, nullable=False)


class SessionHealthStateORM(Base):
    __tablename__ = "session_health_states"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_session_health_states_status_valid",
        ),
        Index("idx_session_health_states_status", "current_status", "last_evaluated_at"),
    )

    scope_key = Column(String, primary_key=True)
    current_status = Column(String, nullable=False)
    latest_alert_codes = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=dict)
    last_evaluated_at = Column(DateTime, default=utc_now, nullable=False)


class LearningHealthStateORM(Base):
    __tablename__ = "learning_health_states"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_learning_health_states_status_valid",
        ),
        Index("idx_learning_health_states_status", "current_status", "last_evaluated_at"),
    )

    scope_key = Column(String, primary_key=True)
    current_status = Column(String, nullable=False)
    latest_alert_codes = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=dict)
    last_evaluated_at = Column(DateTime, default=utc_now, nullable=False)


class ContentQualityCheckORM(Base):
    __tablename__ = "content_quality_checks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('passed', 'rejected')",
            name="ck_content_quality_checks_status_valid",
        ),
        Index("idx_content_quality_checks_source_checked", "source", "checked_at"),
        Index("idx_content_quality_checks_status_checked", "status", "checked_at"),
        Index("idx_content_quality_checks_reference", "reference_id", "checked_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source = Column(String, nullable=False)
    artifact_type = Column(String, nullable=False)
    reference_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    score = Column(Float, nullable=False, default=1.0)
    violations = Column(JSON, nullable=False, default=list)
    artifact_summary = Column(JSON, nullable=False, default=dict)
    checked_at = Column(DateTime, default=utc_now, nullable=False)


class ContentQualityHealthStateORM(Base):
    __tablename__ = "content_quality_health_states"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_content_quality_health_states_status_valid",
        ),
        Index("idx_content_quality_health_states_status", "current_status", "last_evaluated_at"),
    )

    scope_key = Column(String, primary_key=True)
    current_status = Column(String, nullable=False)
    latest_alert_codes = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=dict)
    last_evaluated_at = Column(DateTime, default=utc_now, nullable=False)


class ExerciseTemplateORM(Base):
    __tablename__ = "exercise_templates"
    __table_args__ = (
        UniqueConstraint("template_key", name="uq_exercise_templates_key"),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_exercise_templates_status_valid",
        ),
        Index("idx_exercise_templates_status", "status", "objective", "difficulty"),
        Index("idx_exercise_templates_type", "exercise_type", "status"),
    )

    id = Column(Integer, primary_key=True)
    template_key = Column(String, nullable=False)
    exercise_type = Column(String, nullable=False)
    objective = Column(String, nullable=False)
    difficulty = Column(String, nullable=False)
    status = Column(String, nullable=False, default="active")
    prompt_template = Column(Text, nullable=False)
    answer_source = Column(String, nullable=False)
    choice_count = Column(Integer)
    template_metadata = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)


class ExerciseTemplateAuditORM(Base):
    __tablename__ = "exercise_template_audits"
    __table_args__ = (
        Index("idx_exercise_template_audits_template", "template_key", "created_at"),
        Index("idx_exercise_template_audits_action", "action", "created_at"),
        ForeignKeyConstraint(
            ["template_key"],
            ["exercise_templates.template_key"],
            ondelete="CASCADE",
        ),
    )

    id = Column(Integer, primary_key=True)
    template_key = Column(String, nullable=False)
    action = Column(String, nullable=False)
    changed_by = Column(String, nullable=False)
    change_note = Column(Text, nullable=False)
    previous_config = Column(JSON, nullable=False, default=dict)
    new_config = Column(JSON, nullable=False, default=dict)
    fixture_report = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class ExerciseTemplateHealthStateORM(Base):
    __tablename__ = "exercise_template_health_states"
    __table_args__ = (
        CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_exercise_template_health_states_status_valid",
        ),
        Index("idx_exercise_template_health_states_status", "current_status", "last_evaluated_at"),
    )

    scope_key = Column(String, primary_key=True)
    current_status = Column(String, nullable=False)
    latest_alert_codes = Column(JSON, nullable=False, default=list)
    metrics = Column(JSON, nullable=False, default=dict)
    last_evaluated_at = Column(DateTime, default=utc_now, nullable=False)


class MonetizationOfferEventORM(Base):
    __tablename__ = "monetization_offer_events"
    __table_args__ = (
        Index("idx_monetization_offer_events_user", "user_id", "created_at"),
        Index("idx_monetization_offer_events_type", "event_type", "created_at"),
        Index("idx_monetization_offer_events_offer", "offer_type", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False)
    offer_type = Column(String)
    paywall_type = Column(String)
    strategy = Column(String)
    geography = Column(String)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class DailyMissionORM(Base):
    __tablename__ = "daily_missions"
    __table_args__ = (
        UniqueConstraint("user_id", "mission_date", name="uq_daily_missions_user_date"),
        CheckConstraint("mission_max_sessions >= 1", name="ck_daily_missions_max_sessions_positive"),
        CheckConstraint(
            "status IN ('issued', 'completed', 'expired', 'cancelled')",
            name="ck_daily_missions_status_valid",
        ),
        Index("idx_daily_missions_user_date", "user_id", "mission_date"),
        Index("idx_daily_missions_status", "status", "mission_date"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mission_date = Column(String, nullable=False)
    status = Column(String, nullable=False, default="issued")
    weak_area = Column(String, nullable=False)
    mission_max_sessions = Column(Integer, nullable=False)
    steps = Column(JSON, nullable=False, default=list)
    loss_aversion_message = Column(Text, nullable=False)
    streak_at_issue = Column(Integer, nullable=False, default=0)
    momentum_score = Column(Float, nullable=False, default=0.0)
    notification_preview = Column(JSON, nullable=False, default=dict)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class RewardChestORM(Base):
    __tablename__ = "reward_chests"
    __table_args__ = (
        UniqueConstraint("mission_id", name="uq_reward_chests_mission_id"),
        CheckConstraint(
            "status IN ('locked', 'unlocked', 'claimed', 'expired')",
            name="ck_reward_chests_status_valid",
        ),
        CheckConstraint("xp_reward >= 0", name="ck_reward_chests_xp_reward_nonnegative"),
        Index("idx_reward_chests_user_status", "user_id", "status"),
        Index("idx_reward_chests_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mission_id = Column(Integer, ForeignKey("daily_missions.id", ondelete="CASCADE"), nullable=False, unique=True)
    status = Column(String, nullable=False, default="locked")
    xp_reward = Column(Integer, nullable=False, default=25)
    badge_hint = Column(String, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    unlocked_at = Column(DateTime)
    claimed_at = Column(DateTime)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class UserLifecycleStateORM(Base):
    __tablename__ = "user_lifecycle_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_lifecycle_states_user_id"),
        CheckConstraint(
            "current_stage IN ('new_user', 'activating', 'engaged', 'at_risk', 'churned')",
            name="ck_user_lifecycle_states_stage_valid",
        ),
        CheckConstraint(
            "previous_stage IS NULL OR previous_stage IN ('new_user', 'activating', 'engaged', 'at_risk', 'churned')",
            name="ck_user_lifecycle_states_previous_stage_valid",
        ),
        CheckConstraint("transition_count >= 0", name="ck_user_lifecycle_states_transition_count_nonnegative"),
        Index("idx_user_lifecycle_states_user", "user_id"),
        Index("idx_user_lifecycle_states_stage", "current_stage", "updated_at"),
        Index("idx_user_lifecycle_states_entered_at", "entered_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    current_stage = Column(String, nullable=False)
    previous_stage = Column(String)
    current_reasons = Column(JSON, nullable=False, default=list)
    entered_at = Column(DateTime, default=utc_now, nullable=False)
    last_transition_at = Column(DateTime, default=utc_now, nullable=False)
    last_transition_source = Column(String, nullable=False)
    last_transition_reference_id = Column(String)
    transition_count = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class LifecycleTransitionORM(Base):
    __tablename__ = "lifecycle_transitions"
    __table_args__ = (
        CheckConstraint(
            "from_stage IS NULL OR from_stage IN ('new_user', 'activating', 'engaged', 'at_risk', 'churned')",
            name="ck_lifecycle_transitions_from_stage_valid",
        ),
        CheckConstraint(
            "to_stage IN ('new_user', 'activating', 'engaged', 'at_risk', 'churned')",
            name="ck_lifecycle_transitions_to_stage_valid",
        ),
        Index("idx_lifecycle_transitions_user_created", "user_id", "created_at"),
        Index("idx_lifecycle_transitions_to_stage", "to_stage", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    from_stage = Column(String)
    to_stage = Column(String, nullable=False)
    reasons = Column(JSON, nullable=False, default=list)
    source = Column(String, nullable=False)
    reference_id = Column(String)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class UserLearningStateORM(Base):
    __tablename__ = "user_learning_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_learning_states_user_id"),
        Index("idx_user_learning_states_user", "user_id"),
        Index("idx_user_learning_states_updated_at", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    skills = Column(JSON, nullable=False, default=dict)
    weak_areas = Column(JSON, nullable=False, default=list)
    mastery_percent = Column(Float, default=0.0, nullable=False)
    accuracy_rate = Column(Float, default=0.0, nullable=False)
    response_speed_seconds = Column(Float, default=0.0, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class UserEngagementStateORM(Base):
    __tablename__ = "user_engagement_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_engagement_states_user_id"),
        CheckConstraint("current_streak >= 0", name="ck_user_engagement_states_current_streak_nonnegative"),
        CheckConstraint("longest_streak >= 0", name="ck_user_engagement_states_longest_streak_nonnegative"),
        CheckConstraint("momentum_score >= 0 AND momentum_score <= 1", name="ck_user_engagement_states_momentum_score_range"),
        CheckConstraint("total_sessions >= 0", name="ck_user_engagement_states_total_sessions_nonnegative"),
        CheckConstraint("sessions_last_3_days >= 0", name="ck_user_engagement_states_sessions_last_3_days_nonnegative"),
        CheckConstraint("shields_used_this_week >= 0", name="ck_user_engagement_states_shields_used_nonnegative"),
        Index("idx_user_engagement_states_user", "user_id"),
        Index("idx_user_engagement_states_updated_at", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    current_streak = Column(Integer, default=0, nullable=False)
    longest_streak = Column(Integer, default=0, nullable=False)
    momentum_score = Column(Float, default=0.0, nullable=False)
    total_sessions = Column(Integer, default=0, nullable=False)
    sessions_last_3_days = Column(Integer, default=0, nullable=False)
    last_session_at = Column(DateTime)
    shields_used_this_week = Column(Integer, default=0, nullable=False)
    daily_mission_completed_at = Column(DateTime)
    interaction_stats = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class UserProgressStateORM(Base):
    __tablename__ = "user_progress_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_progress_states_user_id"),
        CheckConstraint("xp >= 0", name="ck_user_progress_states_xp_nonnegative"),
        CheckConstraint("level >= 1", name="ck_user_progress_states_level_min"),
        Index("idx_user_progress_states_user", "user_id"),
        Index("idx_user_progress_states_updated_at", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    xp = Column(Integer, default=0, nullable=False)
    level = Column(Integer, default=1, nullable=False)
    milestones = Column(JSON, nullable=False, default=list)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class LearningSessionORM(Base):
    __tablename__ = "learning_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'expired', 'cancelled')",
            name="ck_learning_sessions_status_valid",
        ),
        CheckConstraint("evaluation_count >= 0", name="ck_learning_sessions_evaluation_count_nonnegative"),
        CheckConstraint(
            "review_window_minutes >= 1",
            name="ck_learning_sessions_review_window_minutes_positive",
        ),
        CheckConstraint(
            "max_response_words >= 1",
            name="ck_learning_sessions_max_response_words_positive",
        ),
        Index("idx_learning_sessions_user_status", "user_id", "status"),
        Index("idx_learning_sessions_user_created", "user_id", "created_at"),
        Index("idx_learning_sessions_expires_at", "expires_at"),
    )

    session_id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, default="active", nullable=False)
    contract_version = Column(String, nullable=False, default="v2")
    duration_seconds = Column(Integer, nullable=False)
    mode = Column(String, nullable=False)
    weak_area = Column(String, nullable=False)
    lesson_target = Column(String)
    goal_label = Column(String, nullable=False)
    success_criteria = Column(Text, nullable=False)
    review_window_minutes = Column(Integer, nullable=False)
    max_response_words = Column(Integer, nullable=False, default=12)
    session_payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    last_evaluated_at = Column(DateTime)
    evaluation_count = Column(Integer, default=0, nullable=False)


class LearningSessionAttemptORM(Base):
    __tablename__ = "learning_session_attempts"
    __table_args__ = (
        CheckConstraint(
            "improvement_score >= 0 AND improvement_score <= 1",
            name="ck_learning_session_attempts_improvement_score_range",
        ),
        CheckConstraint(
            "response_word_count >= 0",
            name="ck_learning_session_attempts_word_count_nonnegative",
        ),
        CheckConstraint(
            "response_char_count >= 0",
            name="ck_learning_session_attempts_char_count_nonnegative",
        ),
        UniqueConstraint("session_id", "submission_id", name="uq_learning_session_attempts_submission"),
        Index("idx_learning_session_attempts_session", "session_id", "created_at"),
        Index("idx_learning_session_attempts_user", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    session_id = Column(String, ForeignKey("learning_sessions.session_id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    submission_id = Column(String, nullable=False)
    learner_response = Column(Text, nullable=False)
    response_word_count = Column(Integer, nullable=False, default=0)
    response_char_count = Column(Integer, nullable=False, default=0)
    is_correct = Column(Boolean, nullable=False)
    improvement_score = Column(Float, nullable=False)
    validation_payload = Column(JSON, nullable=False, default=dict)
    feedback_payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class DecisionTraceORM(Base):
    __tablename__ = "decision_traces"
    __table_args__ = (
        Index("idx_decision_traces_user_type", "user_id", "trace_type", "created_at"),
        Index("idx_decision_traces_reference", "reference_id", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    trace_type = Column(String, nullable=False)
    source = Column(String, nullable=False)
    reference_id = Column(String)
    policy_version = Column(String, nullable=False)
    inputs = Column(JSON, nullable=False, default=dict)
    outputs = Column(JSON, nullable=False, default=dict)
    reason = Column(Text)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class OnboardingFlowStateORM(Base):
    __tablename__ = "onboarding_flow_states"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_onboarding_flow_states_user_id"),
        Index("idx_onboarding_flow_states_user", "user_id"),
        Index("idx_onboarding_flow_states_step", "current_step", "updated_at"),
        Index("idx_onboarding_flow_states_updated_at", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    current_step = Column(String, nullable=False)
    steps_completed = Column(JSON, nullable=False, default=list)
    identity = Column(JSON, nullable=False, default=dict)
    personalization = Column(JSON, nullable=False, default=dict)
    wow = Column(JSON, nullable=False, default=dict)
    early_success_score = Column(Float, default=0.0, nullable=False)
    progress_illusion = Column(JSON, nullable=False, default=dict)
    paywall = Column(JSON, nullable=False, default=dict)
    habit_lock_in = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class UserCoreStateORM(Base):
    __tablename__ = "user_core_state"
    __table_args__ = (
        CheckConstraint("xp >= 0", name="ck_user_core_state_xp_nonnegative"),
        CheckConstraint("level >= 1", name="ck_user_core_state_level_min"),
        CheckConstraint("current_streak >= 0", name="ck_user_core_state_streak_nonnegative"),
        CheckConstraint("longest_streak >= 0", name="ck_user_core_state_longest_streak_nonnegative"),
        CheckConstraint("momentum_score >= 0 AND momentum_score <= 1", name="ck_user_core_state_momentum_range"),
        CheckConstraint("total_sessions >= 0", name="ck_user_core_state_total_sessions_nonnegative"),
        CheckConstraint("sessions_last_3_days >= 0", name="ck_user_core_state_recent_sessions_nonnegative"),
        CheckConstraint("version >= 1", name="ck_user_core_state_version_min"),
        Index("idx_user_core_state_updated", "updated_at"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    xp = Column(Integer, nullable=False, default=0)
    level = Column(Integer, nullable=False, default=1)
    current_streak = Column(Integer, nullable=False, default=0)
    longest_streak = Column(Integer, nullable=False, default=0)
    momentum_score = Column(Float, nullable=False, default=0.0)
    total_sessions = Column(Integer, nullable=False, default=0)
    sessions_last_3_days = Column(Integer, nullable=False, default=0)
    version = Column(Integer, nullable=False, default=1)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class MutationLedgerORM(Base):
    __tablename__ = "mutation_ledger"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "idempotency_key", name="pk_mutation_ledger"),
        Index("idx_mutation_ledger_user", "user_id"),
        Index("idx_mutation_ledger_created", "created_at"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    idempotency_key = Column(String, nullable=False)
    source = Column(String, nullable=False)
    reference_id = Column(String)
    result_code = Column(Integer)
    result_hash = Column(String)
    response_etag = Column(String)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class OutboxEventORM(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
        Index("idx_outbox_unpublished", "published_at", "next_attempt_at", "id"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    dedupe_key = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    published_at = Column(DateTime)
    retry_count = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=False, default=utc_now)


class UserMutationQueueORM(Base):
    __tablename__ = "user_mutation_queue"
    __table_args__ = (
        UniqueConstraint("user_id", "seq", name="uq_user_mutation_queue_seq"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_user_mutation_queue_idempotency"),
        Index("idx_user_queue_user", "user_id", "seq"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    seq = Column(BigInteger, nullable=False)
    idempotency_key = Column(String, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class UserQueueSeqORM(Base):
    __tablename__ = "user_queue_seq"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    next_seq = Column(BigInteger, nullable=False, default=1)
    last_applied_seq = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class UserExecutionModeORM(Base):
    __tablename__ = "user_execution_mode"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    mode = Column(String, nullable=False, default="cold")
    updated_at = Column(DateTime, default=utc_now, nullable=False)


class LearningStateCursorORM(Base):
    __tablename__ = "learning_state_cursors"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    last_processed_attempt_id = Column(BigInteger, nullable=False, default=0)
