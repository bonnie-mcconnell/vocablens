"""add notification delivery and subscription event tracking

Revision ID: 20260318_0005
Revises: 20260318_0004
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260318_0005"
down_revision = "20260318_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text()),
        sa.Column("error_message", sa.Text()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_notification_delivery_user", "notification_deliveries", ["user_id", "created_at"])
    op.create_index("idx_notification_delivery_status", "notification_deliveries", ["status", "created_at"])

    op.create_table(
        "subscription_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("from_tier", sa.String()),
        sa.Column("to_tier", sa.String()),
        sa.Column("feature_name", sa.String()),
        sa.Column("metadata_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_subscription_events_user", "subscription_events", ["user_id", "created_at"])
    op.create_index("idx_subscription_events_type", "subscription_events", ["event_type", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_subscription_events_type", table_name="subscription_events")
    op.drop_index("idx_subscription_events_user", table_name="subscription_events")
    op.drop_table("subscription_events")

    op.drop_index("idx_notification_delivery_status", table_name="notification_deliveries")
    op.drop_index("idx_notification_delivery_user", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
