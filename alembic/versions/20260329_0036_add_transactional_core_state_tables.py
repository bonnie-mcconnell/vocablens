"""add transactional core state tables

Revision ID: 20260329_0036
Revises: 20260325_0035
Create Date: 2026-03-29 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260329_0036"
down_revision = "20260325_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_core_state",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("longest_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("momentum_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sessions_last_3_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint("xp >= 0", name="ck_user_core_state_xp_nonnegative"),
        sa.CheckConstraint("level >= 1", name="ck_user_core_state_level_min"),
        sa.CheckConstraint("current_streak >= 0", name="ck_user_core_state_streak_nonnegative"),
        sa.CheckConstraint("longest_streak >= 0", name="ck_user_core_state_longest_streak_nonnegative"),
        sa.CheckConstraint("momentum_score >= 0 AND momentum_score <= 1", name="ck_user_core_state_momentum_range"),
        sa.CheckConstraint("total_sessions >= 0", name="ck_user_core_state_total_sessions_nonnegative"),
        sa.CheckConstraint("sessions_last_3_days >= 0", name="ck_user_core_state_recent_sessions_nonnegative"),
        sa.CheckConstraint("version >= 1", name="ck_user_core_state_version_min"),
    )
    op.create_index("idx_user_core_state_updated", "user_core_state", ["updated_at"], unique=False)

    op.create_table(
        "mutation_ledger",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("reference_id", sa.String(), nullable=True),
        sa.Column("result_code", sa.Integer(), nullable=True),
        sa.Column("result_hash", sa.String(), nullable=True),
        sa.Column("response_etag", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "idempotency_key", name="pk_mutation_ledger"),
    )
    op.create_index("idx_mutation_ledger_user", "mutation_ledger", ["user_id"], unique=False)
    op.create_index("idx_mutation_ledger_created", "mutation_ledger", ["created_at"], unique=False)

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
    )
    op.create_index("idx_outbox_unpublished", "outbox_events", ["published_at", "next_attempt_at", "id"], unique=False)

    op.create_table(
        "user_mutation_queue",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "seq", name="uq_user_mutation_queue_seq"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_user_mutation_queue_idempotency"),
    )
    op.create_index("idx_user_queue_user", "user_mutation_queue", ["user_id", "seq"], unique=False)

    op.create_table(
        "learning_state_cursors",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("last_processed_attempt_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "user_queue_seq",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("next_seq", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "user_queue_progress",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("last_applied_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "user_execution_mode",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False, server_default="cold"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_execution_mode")
    op.drop_table("user_queue_progress")
    op.drop_table("user_queue_seq")

    op.drop_table("learning_state_cursors")

    op.drop_index("idx_user_queue_user", table_name="user_mutation_queue")
    op.drop_table("user_mutation_queue")

    op.drop_index("idx_outbox_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")

    op.drop_index("idx_mutation_ledger_created", table_name="mutation_ledger")
    op.drop_index("idx_mutation_ledger_user", table_name="mutation_ledger")
    op.drop_table("mutation_ledger")

    op.drop_index("idx_user_core_state_updated", table_name="user_core_state")
    op.drop_table("user_core_state")
