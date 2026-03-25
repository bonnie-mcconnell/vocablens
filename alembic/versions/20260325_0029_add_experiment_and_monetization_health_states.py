"""add experiment and monetization health states

Revision ID: 20260325_0029
Revises: 20260325_0028
Create Date: 2026-03-25 16:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0029"
down_revision = "20260325_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_health_states",
        sa.Column("experiment_key", sa.String(), nullable=False),
        sa.Column("current_status", sa.String(), nullable=False),
        sa.Column("latest_alert_codes", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["experiment_key"], ["experiment_registries.experiment_key"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("experiment_key"),
        sa.CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_experiment_health_states_status_valid",
        ),
    )
    op.create_index(
        "idx_experiment_health_states_status",
        "experiment_health_states",
        ["current_status", "last_evaluated_at"],
        unique=False,
    )

    op.create_table(
        "monetization_health_states",
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("current_status", sa.String(), nullable=False),
        sa.Column("latest_alert_codes", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("scope_key"),
        sa.CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_monetization_health_states_status_valid",
        ),
    )
    op.create_index(
        "idx_monetization_health_states_status",
        "monetization_health_states",
        ["current_status", "last_evaluated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_monetization_health_states_status", table_name="monetization_health_states")
    op.drop_table("monetization_health_states")
    op.drop_index("idx_experiment_health_states_status", table_name="experiment_health_states")
    op.drop_table("experiment_health_states")
