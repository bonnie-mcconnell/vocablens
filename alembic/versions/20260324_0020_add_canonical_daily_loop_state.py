"""add canonical daily loop state

Revision ID: 20260324_0020
Revises: 20260324_0019
Create Date: 2026-03-24 11:45:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0020"
down_revision = "20260324_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_missions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mission_date", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="issued"),
        sa.Column("weak_area", sa.String(), nullable=False),
        sa.Column("mission_max_sessions", sa.Integer(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("loss_aversion_message", sa.Text(), nullable=False),
        sa.Column("streak_at_issue", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("momentum_score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("notification_preview", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("mission_max_sessions >= 1", name="ck_daily_missions_max_sessions_positive"),
        sa.CheckConstraint(
            "status IN ('issued', 'completed', 'expired', 'cancelled')",
            name="ck_daily_missions_status_valid",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "mission_date", name="uq_daily_missions_user_date"),
    )
    op.create_index("idx_daily_missions_user_date", "daily_missions", ["user_id", "mission_date"], unique=False)
    op.create_index("idx_daily_missions_status", "daily_missions", ["status", "mission_date"], unique=False)

    op.create_table(
        "reward_chests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mission_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="locked"),
        sa.Column("xp_reward", sa.Integer(), nullable=False, server_default=sa.text("25")),
        sa.Column("badge_hint", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("unlocked_at", sa.DateTime(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('locked', 'unlocked', 'claimed', 'expired')",
            name="ck_reward_chests_status_valid",
        ),
        sa.CheckConstraint("xp_reward >= 0", name="ck_reward_chests_xp_reward_nonnegative"),
        sa.ForeignKeyConstraint(["mission_id"], ["daily_missions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id", name="uq_reward_chests_mission_id"),
    )
    op.create_index("idx_reward_chests_user_status", "reward_chests", ["user_id", "status"], unique=False)
    op.create_index("idx_reward_chests_created_at", "reward_chests", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_reward_chests_created_at", table_name="reward_chests")
    op.drop_index("idx_reward_chests_user_status", table_name="reward_chests")
    op.drop_table("reward_chests")
    op.drop_index("idx_daily_missions_status", table_name="daily_missions")
    op.drop_index("idx_daily_missions_user_date", table_name="daily_missions")
    op.drop_table("daily_missions")
