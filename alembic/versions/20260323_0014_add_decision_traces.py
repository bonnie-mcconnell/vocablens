"""add decision traces

Revision ID: 20260323_0014
Revises: 20260323_0013
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_0014"
down_revision = "20260323_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_traces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("trace_type", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("reference_id", sa.String(), nullable=True),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("outputs", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_decision_traces_user_type",
        "decision_traces",
        ["user_id", "trace_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_decision_traces_reference",
        "decision_traces",
        ["reference_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_decision_traces_reference", table_name="decision_traces")
    op.drop_index("idx_decision_traces_user_type", table_name="decision_traces")
    op.drop_table("decision_traces")
