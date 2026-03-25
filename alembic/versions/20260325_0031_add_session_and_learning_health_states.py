"""add session and learning health states

Revision ID: 20260325_0031
Revises: 20260325_0030
Create Date: 2026-03-25 19:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0031"
down_revision = "20260325_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_health_states",
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("current_status", sa.String(), nullable=False),
        sa.Column("latest_alert_codes", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("scope_key"),
        sa.CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_session_health_states_status_valid",
        ),
    )
    op.create_index(
        "idx_session_health_states_status",
        "session_health_states",
        ["current_status", "last_evaluated_at"],
        unique=False,
    )

    op.create_table(
        "learning_health_states",
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("current_status", sa.String(), nullable=False),
        sa.Column("latest_alert_codes", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("scope_key"),
        sa.CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_learning_health_states_status_valid",
        ),
    )
    op.create_index(
        "idx_learning_health_states_status",
        "learning_health_states",
        ["current_status", "last_evaluated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_learning_health_states_status", table_name="learning_health_states")
    op.drop_table("learning_health_states")
    op.drop_index("idx_session_health_states_status", table_name="session_health_states")
    op.drop_table("session_health_states")
