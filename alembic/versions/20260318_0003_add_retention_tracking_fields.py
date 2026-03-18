"""add retention tracking fields to user profiles

Revision ID: 20260318_0003
Revises: 20260318_0002
Create Date: 2026-03-18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260318_0003"
down_revision = "20260318_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch_op:
        batch_op.add_column(
            sa.Column("last_active_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        batch_op.add_column(
            sa.Column("session_frequency", sa.Float(), nullable=False, server_default="0"),
        )
        batch_op.add_column(
            sa.Column("current_streak", sa.Integer(), nullable=False, server_default="0"),
        )
        batch_op.add_column(
            sa.Column("longest_streak", sa.Integer(), nullable=False, server_default="0"),
        )
        batch_op.add_column(
            sa.Column("drop_off_risk", sa.Float(), nullable=False, server_default="0"),
        )
        batch_op.create_index("idx_user_profile_last_active_at", ["last_active_at"])
        batch_op.create_index("idx_user_profile_drop_off_risk", ["drop_off_risk"])
        batch_op.create_check_constraint(
            "ck_user_profiles_session_frequency_nonnegative",
            "session_frequency >= 0",
        )
        batch_op.create_check_constraint(
            "ck_user_profiles_current_streak_nonnegative",
            "current_streak >= 0",
        )
        batch_op.create_check_constraint(
            "ck_user_profiles_longest_streak_nonnegative",
            "longest_streak >= 0",
        )
        batch_op.create_check_constraint(
            "ck_user_profiles_drop_off_risk_range",
            "drop_off_risk >= 0 AND drop_off_risk <= 1",
        )


def downgrade() -> None:
    with op.batch_alter_table("user_profiles") as batch_op:
        batch_op.drop_constraint("ck_user_profiles_drop_off_risk_range", type_="check")
        batch_op.drop_constraint("ck_user_profiles_longest_streak_nonnegative", type_="check")
        batch_op.drop_constraint("ck_user_profiles_current_streak_nonnegative", type_="check")
        batch_op.drop_constraint("ck_user_profiles_session_frequency_nonnegative", type_="check")
        batch_op.drop_index("idx_user_profile_drop_off_risk")
        batch_op.drop_index("idx_user_profile_last_active_at")
        batch_op.drop_column("drop_off_risk")
        batch_op.drop_column("longest_streak")
        batch_op.drop_column("current_streak")
        batch_op.drop_column("session_frequency")
        batch_op.drop_column("last_active_at")
