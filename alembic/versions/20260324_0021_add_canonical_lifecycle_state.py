"""add canonical lifecycle state

Revision ID: 20260324_0021
Revises: 20260324_0020
Create Date: 2026-03-24 13:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0021"
down_revision = "20260324_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_lifecycle_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("current_stage", sa.String(), nullable=False),
        sa.Column("previous_stage", sa.String(), nullable=True),
        sa.Column("current_reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("entered_at", sa.DateTime(), nullable=False),
        sa.Column("last_transition_at", sa.DateTime(), nullable=False),
        sa.Column("last_transition_source", sa.String(), nullable=False),
        sa.Column("last_transition_reference_id", sa.String(), nullable=True),
        sa.Column("transition_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "current_stage IN ('new_user', 'activating', 'engaged', 'at_risk', 'churned')",
            name="ck_user_lifecycle_states_stage_valid",
        ),
        sa.CheckConstraint(
            "previous_stage IS NULL OR previous_stage IN ('new_user', 'activating', 'engaged', 'at_risk', 'churned')",
            name="ck_user_lifecycle_states_previous_stage_valid",
        ),
        sa.CheckConstraint(
            "transition_count >= 0",
            name="ck_user_lifecycle_states_transition_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_lifecycle_states_user_id"),
    )
    op.create_index("idx_user_lifecycle_states_user", "user_lifecycle_states", ["user_id"], unique=False)
    op.create_index(
        "idx_user_lifecycle_states_stage",
        "user_lifecycle_states",
        ["current_stage", "updated_at"],
        unique=False,
    )
    op.create_index(
        "idx_user_lifecycle_states_entered_at",
        "user_lifecycle_states",
        ["entered_at"],
        unique=False,
    )

    op.create_table(
        "lifecycle_transitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("from_stage", sa.String(), nullable=True),
        sa.Column("to_stage", sa.String(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("reference_id", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "from_stage IS NULL OR from_stage IN ('new_user', 'activating', 'engaged', 'at_risk', 'churned')",
            name="ck_lifecycle_transitions_from_stage_valid",
        ),
        sa.CheckConstraint(
            "to_stage IN ('new_user', 'activating', 'engaged', 'at_risk', 'churned')",
            name="ck_lifecycle_transitions_to_stage_valid",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_lifecycle_transitions_user_created",
        "lifecycle_transitions",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_lifecycle_transitions_to_stage",
        "lifecycle_transitions",
        ["to_stage", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_lifecycle_transitions_to_stage", table_name="lifecycle_transitions")
    op.drop_index("idx_lifecycle_transitions_user_created", table_name="lifecycle_transitions")
    op.drop_table("lifecycle_transitions")
    op.drop_index("idx_user_lifecycle_states_entered_at", table_name="user_lifecycle_states")
    op.drop_index("idx_user_lifecycle_states_stage", table_name="user_lifecycle_states")
    op.drop_index("idx_user_lifecycle_states_user", table_name="user_lifecycle_states")
    op.drop_table("user_lifecycle_states")
