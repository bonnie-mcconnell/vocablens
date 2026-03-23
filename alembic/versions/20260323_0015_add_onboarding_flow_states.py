"""add onboarding flow states

Revision ID: 20260323_0015
Revises: 20260323_0014
Create Date: 2026-03-23 12:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_0015"
down_revision = "20260323_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "onboarding_flow_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("current_step", sa.String(), nullable=False),
        sa.Column("steps_completed", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("identity", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("personalization", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("wow", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("early_success_score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("progress_illusion", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("paywall", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("habit_lock_in", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_onboarding_flow_states_user_id"),
    )
    op.create_index(
        "idx_onboarding_flow_states_user",
        "onboarding_flow_states",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "idx_onboarding_flow_states_step",
        "onboarding_flow_states",
        ["current_step", "updated_at"],
        unique=False,
    )
    op.create_index(
        "idx_onboarding_flow_states_updated_at",
        "onboarding_flow_states",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_onboarding_flow_states_updated_at", table_name="onboarding_flow_states")
    op.drop_index("idx_onboarding_flow_states_step", table_name="onboarding_flow_states")
    op.drop_index("idx_onboarding_flow_states_user", table_name="onboarding_flow_states")
    op.drop_table("onboarding_flow_states")
