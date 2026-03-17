from datetime import datetime
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
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class UserORM(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    vocabulary = relationship("VocabularyORM", back_populates="user")


class VocabularyORM(Base):
    __tablename__ = "vocabulary"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    source_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=False)
    source_lang = Column(String, nullable=False)
    target_lang = Column(String, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_reviewed_at = Column(DateTime)
    review_count = Column(Integer, default=0, nullable=False)
    ease_factor = Column(Float, default=2.5, nullable=False)
    interval = Column(Integer, default=1, nullable=False)
    repetitions = Column(Integer, default=0, nullable=False)
    next_review_due = Column(DateTime)

    example_source_sentence = Column(Text)
    example_translated_sentence = Column(Text)
    grammar_note = Column(Text)
    semantic_cluster = Column(Text)

    user = relationship("UserORM", back_populates="vocabulary")


Index("idx_vocab_user_id", VocabularyORM.user_id)
Index("idx_vocab_next_due", VocabularyORM.next_review_due)
Index("idx_vocab_cluster", VocabularyORM.semantic_cluster)


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
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("idx_conversation_history_user", ConversationHistoryORM.user_id, ConversationHistoryORM.created_at)


class SkillTrackingORM(Base):
    __tablename__ = "skill_tracking"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    skill = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("idx_skill_tracking_user", SkillTrackingORM.user_id, SkillTrackingORM.created_at)


class LearningEventORM(Base):
    __tablename__ = "learning_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String, nullable=False)
    payload_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("idx_learning_events_user", LearningEventORM.user_id, LearningEventORM.created_at)


class KnowledgeGraphEdgeORM(Base):
    __tablename__ = "knowledge_graph_edges"

    id = Column(Integer, primary_key=True)
    source_node = Column(Text, nullable=False)
    target_node = Column(Text, nullable=False)
    relation_type = Column(String, nullable=False)
    weight = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("idx_kge_source", KnowledgeGraphEdgeORM.source_node, KnowledgeGraphEdgeORM.relation_type)


class EmbeddingORM(Base):
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True)
    word = Column(Text, nullable=False, unique=True)
    embedding = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("idx_embeddings_word", EmbeddingORM.word)


class UsageLogORM(Base):
    __tablename__ = "usage_logs"

    id = Column(BigInteger, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    endpoint = Column(String, nullable=False)
    tokens_used = Column(Integer, default=0, nullable=False)
    success = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("idx_usage_user_day", UsageLogORM.user_id, UsageLogORM.created_at)
Index("idx_usage_endpoint", UsageLogORM.endpoint)


class SubscriptionORM(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    tier = Column(String, default="free", nullable=False)
    request_limit = Column(Integer, default=100, nullable=False)
    token_limit = Column(Integer, default=50000, nullable=False)
    renewed_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("idx_subscription_user", SubscriptionORM.user_id)


class MistakePatternORM(Base):
    __tablename__ = "mistake_patterns"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category = Column(String, nullable=False)  # grammar | vocabulary | repetition
    pattern = Column(Text, nullable=False)
    count = Column(Integer, default=1, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("idx_mistake_user_category", MistakePatternORM.user_id, MistakePatternORM.category)
