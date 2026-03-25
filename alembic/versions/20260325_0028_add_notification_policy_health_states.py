"""add notification policy health states

Revision ID: 20260325_0028
Revises: 20260325_0027
Create Date: 2026-03-25 14:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0028"
down_revision = "20260325_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_policy_health_states",
        sa.Column("policy_key", sa.String(), nullable=False),
        sa.Column("current_status", sa.String(), nullable=False),
        sa.Column("latest_alert_codes", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["policy_key"], ["notification_policy_registries.policy_key"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("policy_key"),
        sa.CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_notification_policy_health_states_status_valid",
        ),
    )
    op.create_index(
        "idx_notification_policy_health_states_status",
        "notification_policy_health_states",
        ["current_status", "last_evaluated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_notification_policy_health_states_status", table_name="notification_policy_health_states")
    op.drop_table("notification_policy_health_states")
