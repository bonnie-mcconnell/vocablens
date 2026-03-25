"""add notification policy attribution fields

Revision ID: 20260325_0027
Revises: 20260324_0026
Create Date: 2026-03-25 11:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0027"
down_revision = "20260324_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notification_deliveries", sa.Column("policy_key", sa.String(), nullable=True))
    op.add_column("notification_deliveries", sa.Column("policy_version", sa.String(), nullable=True))
    op.add_column("notification_deliveries", sa.Column("source_context", sa.String(), nullable=True))
    op.add_column("notification_deliveries", sa.Column("reference_id", sa.String(), nullable=True))
    op.create_index(
        "idx_notification_delivery_policy",
        "notification_deliveries",
        ["policy_key", "policy_version", "created_at"],
        unique=False,
    )

    op.add_column("notification_suppression_events", sa.Column("policy_key", sa.String(), nullable=True))
    op.add_column("notification_suppression_events", sa.Column("policy_version", sa.String(), nullable=True))
    op.create_index(
        "idx_notification_suppression_events_policy",
        "notification_suppression_events",
        ["policy_key", "policy_version", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_notification_suppression_events_policy", table_name="notification_suppression_events")
    op.drop_column("notification_suppression_events", "policy_version")
    op.drop_column("notification_suppression_events", "policy_key")

    op.drop_index("idx_notification_delivery_policy", table_name="notification_deliveries")
    op.drop_column("notification_deliveries", "reference_id")
    op.drop_column("notification_deliveries", "source_context")
    op.drop_column("notification_deliveries", "policy_version")
    op.drop_column("notification_deliveries", "policy_key")
