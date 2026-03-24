"""add experiment outcome attributions

Revision ID: 20260324_0024
Revises: 20260324_0023
Create Date: 2026-03-24 00:24:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0024"
down_revision = "20260324_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_outcome_attributions",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("experiment_key", sa.String(), nullable=False),
        sa.Column("variant", sa.String(), nullable=False),
        sa.Column("assignment_reason", sa.String(), nullable=False, server_default="rollout"),
        sa.Column("attribution_version", sa.String(), nullable=False, server_default="v1"),
        sa.Column("exposed_at", sa.DateTime(), nullable=False),
        sa.Column("window_end_at", sa.DateTime(), nullable=False),
        sa.Column("retained_d1", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retained_d7", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("converted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("first_conversion_at", sa.DateTime(), nullable=True),
        sa.Column("session_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("learning_action_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("upgrade_click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_event_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "session_count >= 0",
            name="ck_experiment_outcome_attributions_session_count_nonnegative",
        ),
        sa.CheckConstraint(
            "message_count >= 0",
            name="ck_experiment_outcome_attributions_message_count_nonnegative",
        ),
        sa.CheckConstraint(
            "learning_action_count >= 0",
            name="ck_experiment_outcome_attributions_learning_action_count_nonnegative",
        ),
        sa.CheckConstraint(
            "upgrade_click_count >= 0",
            name="ck_experiment_outcome_attributions_upgrade_click_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "experiment_key", name="pk_experiment_outcome_attributions"),
    )
    op.create_index(
        "idx_experiment_outcome_attributions_variant",
        "experiment_outcome_attributions",
        ["experiment_key", "variant"],
    )
    op.create_index(
        "idx_experiment_outcome_attributions_window_end",
        "experiment_outcome_attributions",
        ["window_end_at"],
    )
    op.create_index(
        "idx_experiment_outcome_attributions_conversion",
        "experiment_outcome_attributions",
        ["experiment_key", "converted"],
    )


def downgrade() -> None:
    op.drop_index("idx_experiment_outcome_attributions_conversion", table_name="experiment_outcome_attributions")
    op.drop_index("idx_experiment_outcome_attributions_window_end", table_name="experiment_outcome_attributions")
    op.drop_index("idx_experiment_outcome_attributions_variant", table_name="experiment_outcome_attributions")
    op.drop_table("experiment_outcome_attributions")
