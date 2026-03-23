"""add experiment exposures

Revision ID: 20260323_0016
Revises: 20260323_0015
Create Date: 2026-03-23 13:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_0016"
down_revision = "20260323_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_exposures",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("experiment_key", sa.String(), nullable=False),
        sa.Column("variant", sa.String(), nullable=False),
        sa.Column("exposed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "experiment_key", name="pk_experiment_exposures"),
    )
    op.create_index(
        "idx_experiment_exposures_variant",
        "experiment_exposures",
        ["experiment_key", "variant"],
        unique=False,
    )
    op.create_index(
        "idx_experiment_exposures_exposed_at",
        "experiment_exposures",
        ["exposed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_experiment_exposures_exposed_at", table_name="experiment_exposures")
    op.drop_index("idx_experiment_exposures_variant", table_name="experiment_exposures")
    op.drop_table("experiment_exposures")
