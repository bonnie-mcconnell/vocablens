"""add lifecycle and daily loop health states

Revision ID: 20260325_0030
Revises: 20260325_0029
Create Date: 2026-03-25 18:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0030"
down_revision = "20260325_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lifecycle_health_states",
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("current_status", sa.String(), nullable=False),
        sa.Column("latest_alert_codes", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("scope_key"),
        sa.CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_lifecycle_health_states_status_valid",
        ),
    )
    op.create_index(
        "idx_lifecycle_health_states_status",
        "lifecycle_health_states",
        ["current_status", "last_evaluated_at"],
        unique=False,
    )

    op.create_table(
        "daily_loop_health_states",
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("current_status", sa.String(), nullable=False),
        sa.Column("latest_alert_codes", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("scope_key"),
        sa.CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_daily_loop_health_states_status_valid",
        ),
    )
    op.create_index(
        "idx_daily_loop_health_states_status",
        "daily_loop_health_states",
        ["current_status", "last_evaluated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_daily_loop_health_states_status", table_name="daily_loop_health_states")
    op.drop_table("daily_loop_health_states")
    op.drop_index("idx_lifecycle_health_states_status", table_name="lifecycle_health_states")
    op.drop_table("lifecycle_health_states")
