"""initial async postgres schema

Revision ID: 20260317_0001
Revises:
Create Date: 2026-03-17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260317_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "vocabulary",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("source_lang", sa.String(), nullable=False),
        sa.Column("target_lang", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_reviewed_at", sa.DateTime()),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ease_factor", sa.Float(), nullable=False, server_default="2.5"),
        sa.Column("interval", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("repetitions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_review_due", sa.DateTime()),
        sa.Column("example_source_sentence", sa.Text()),
        sa.Column("example_translated_sentence", sa.Text()),
        sa.Column("grammar_note", sa.Text()),
        sa.Column("semantic_cluster", sa.Text()),
    )
    op.create_index("idx_vocab_user_id", "vocabulary", ["user_id"])
    op.create_index("idx_vocab_next_due", "vocabulary", ["next_review_due"])
    op.create_index("idx_vocab_cluster", "vocabulary", ["semantic_cluster"])

    op.create_table(
        "translation_cache",
        sa.Column("text", sa.Text(), primary_key=True),
        sa.Column("source_lang", sa.String(), primary_key=True),
        sa.Column("target_lang", sa.String(), primary_key=True),
        sa.Column("translation", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_translation_cache_langs",
        "translation_cache",
        ["source_lang", "target_lang"],
    )

    op.create_table(
        "conversation_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_conversation_history_user",
        "conversation_history",
        ["user_id", "created_at"],
    )

    op.create_table(
        "skill_tracking",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_skill_tracking_user", "skill_tracking", ["user_id", "created_at"])

    op.create_table(
        "learning_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_learning_events_user", "learning_events", ["user_id", "created_at"])

    op.create_table(
        "knowledge_graph_edges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_node", sa.Text(), nullable=False),
        sa.Column("target_node", sa.Text(), nullable=False),
        sa.Column("relation_type", sa.String(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "idx_kge_source",
        "knowledge_graph_edges",
        ["source_node", "relation_type"],
    )

    op.create_table(
        "embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("word", sa.Text(), nullable=False, unique=True),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_embeddings_word", "embeddings", ["word"])


def downgrade() -> None:
    op.drop_index("idx_embeddings_word", table_name="embeddings")
    op.drop_table("embeddings")

    op.drop_index("idx_kge_source", table_name="knowledge_graph_edges")
    op.drop_table("knowledge_graph_edges")

    op.drop_index("idx_learning_events_user", table_name="learning_events")
    op.drop_table("learning_events")

    op.drop_index("idx_skill_tracking_user", table_name="skill_tracking")
    op.drop_table("skill_tracking")

    op.drop_index("idx_conversation_history_user", table_name="conversation_history")
    op.drop_table("conversation_history")

    op.drop_index("idx_translation_cache_langs", table_name="translation_cache")
    op.drop_table("translation_cache")

    op.drop_index("idx_vocab_cluster", table_name="vocabulary")
    op.drop_index("idx_vocab_next_due", table_name="vocabulary")
    op.drop_index("idx_vocab_user_id", table_name="vocabulary")
    op.drop_table("vocabulary")

    op.drop_table("users")
