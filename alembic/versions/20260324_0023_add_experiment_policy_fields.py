"""add experiment policy fields

Revision ID: 20260324_0023
Revises: 20260324_0022
Create Date: 2026-03-24 15:10:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0023"
down_revision = "20260324_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("experiment_registries") as batch_op:
        batch_op.add_column(
            sa.Column("holdout_percentage", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
        batch_op.add_column(
            sa.Column("baseline_variant", sa.String(), nullable=False, server_default="control"),
        )
        batch_op.add_column(
            sa.Column("eligibility", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )
        batch_op.add_column(
            sa.Column("mutually_exclusive_with", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
        batch_op.add_column(
            sa.Column("prerequisite_experiments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
        batch_op.create_check_constraint(
            "ck_experiment_registries_holdout_percentage_range",
            "holdout_percentage >= 0 AND holdout_percentage <= 100",
        )


def downgrade() -> None:
    with op.batch_alter_table("experiment_registries") as batch_op:
        batch_op.drop_constraint("ck_experiment_registries_holdout_percentage_range", type_="check")
        batch_op.drop_column("prerequisite_experiments")
        batch_op.drop_column("mutually_exclusive_with")
        batch_op.drop_column("eligibility")
        batch_op.drop_column("baseline_variant")
        batch_op.drop_column("holdout_percentage")
