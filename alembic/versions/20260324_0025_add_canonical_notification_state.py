"""add canonical notification state

Revision ID: 20260324_0025
Revises: 20260324_0024
Create Date: 2026-03-24 16:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0025"
down_revision = "20260324_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_notification_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("preferred_channel", sa.String(), nullable=False, server_default="push"),
        sa.Column("preferred_time_of_day", sa.Integer(), nullable=False, server_default=sa.text("18")),
        sa.Column("frequency_limit", sa.Integer(), nullable=False, server_default=sa.text("2")),
        sa.Column("lifecycle_stage", sa.String(), nullable=True),
        sa.Column("lifecycle_policy_version", sa.String(), nullable=False, server_default="v1"),
        sa.Column("lifecycle_policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("suppression_reason", sa.Text(), nullable=True),
        sa.Column("suppressed_until", sa.DateTime(), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(), nullable=True),
        sa.Column("sent_count_day", sa.String(), nullable=True),
        sa.Column("sent_count_today", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_delivery_channel", sa.String(), nullable=True),
        sa.Column("last_delivery_status", sa.String(), nullable=True),
        sa.Column("last_delivery_category", sa.String(), nullable=True),
        sa.Column("last_reference_id", sa.String(), nullable=True),
        sa.Column("last_decision_at", sa.DateTime(), nullable=True),
        sa.Column("last_decision_reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "preferred_channel IN ('email', 'push', 'in_app')",
            name="ck_user_notification_states_preferred_channel_valid",
        ),
        sa.CheckConstraint(
            "preferred_time_of_day >= 0 AND preferred_time_of_day <= 23",
            name="ck_user_notification_states_preferred_time_of_day_range",
        ),
        sa.CheckConstraint(
            "frequency_limit >= 0",
            name="ck_user_notification_states_frequency_limit_nonnegative",
        ),
        sa.CheckConstraint(
            "sent_count_today >= 0",
            name="ck_user_notification_states_sent_count_today_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_notification_states_user_id"),
    )
    op.create_index("idx_user_notification_states_user", "user_notification_states", ["user_id"], unique=False)
    op.create_index(
        "idx_user_notification_states_updated_at",
        "user_notification_states",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "idx_user_notification_states_cooldown_until",
        "user_notification_states",
        ["cooldown_until"],
        unique=False,
    )
    op.create_index(
        "idx_user_notification_states_suppressed_until",
        "user_notification_states",
        ["suppressed_until"],
        unique=False,
    )
    op.create_index(
        "idx_user_notification_states_lifecycle_stage",
        "user_notification_states",
        ["lifecycle_stage", "updated_at"],
        unique=False,
    )

    op.create_table(
        "notification_suppression_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("reference_id", sa.String(), nullable=True),
        sa.Column("lifecycle_stage", sa.String(), nullable=True),
        sa.Column("suppression_reason", sa.Text(), nullable=True),
        sa.Column("suppressed_until", sa.DateTime(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_notification_suppression_events_user",
        "notification_suppression_events",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_notification_suppression_events_source",
        "notification_suppression_events",
        ["source", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_notification_suppression_events_stage",
        "notification_suppression_events",
        ["lifecycle_stage", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_notification_suppression_events_stage", table_name="notification_suppression_events")
    op.drop_index("idx_notification_suppression_events_source", table_name="notification_suppression_events")
    op.drop_index("idx_notification_suppression_events_user", table_name="notification_suppression_events")
    op.drop_table("notification_suppression_events")
    op.drop_index("idx_user_notification_states_lifecycle_stage", table_name="user_notification_states")
    op.drop_index("idx_user_notification_states_suppressed_until", table_name="user_notification_states")
    op.drop_index("idx_user_notification_states_cooldown_until", table_name="user_notification_states")
    op.drop_index("idx_user_notification_states_updated_at", table_name="user_notification_states")
    op.drop_index("idx_user_notification_states_user", table_name="user_notification_states")
    op.drop_table("user_notification_states")
