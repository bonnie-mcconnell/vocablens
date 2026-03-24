"""add experiment registry audits

Revision ID: 20260324_0018
Revises: 20260323_0017
Create Date: 2026-03-24 10:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0018"
down_revision = "20260323_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_registry_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("experiment_key", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("changed_by", sa.String(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=False),
        sa.Column("previous_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("new_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_key"],
            ["experiment_registries.experiment_key"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_experiment_registry_audits_experiment",
        "experiment_registry_audits",
        ["experiment_key", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_experiment_registry_audits_action",
        "experiment_registry_audits",
        ["action", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_experiment_registry_audits_action", table_name="experiment_registry_audits")
    op.drop_index("idx_experiment_registry_audits_experiment", table_name="experiment_registry_audits")
    op.drop_table("experiment_registry_audits")
