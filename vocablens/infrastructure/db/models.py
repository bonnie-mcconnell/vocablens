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
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    status = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    payload_json = Column(Text)
    error_message = Column(Text)
    attempt_count = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)


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
