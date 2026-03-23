"""add learning session tables

Revision ID: 20260323_0013
Revises: 20260321_0012
Create Date: 2026-03-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260323_0013"
down_revision = "20260321_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learning_sessions",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("weak_area", sa.String(), nullable=False),
        sa.Column("lesson_target", sa.String(), nullable=True),
        sa.Column("goal_label", sa.String(), nullable=False),
        sa.Column("success_criteria", sa.Text(), nullable=False),
        sa.Column("review_window_minutes", sa.Integer(), nullable=False),
        sa.Column("session_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=True),
        sa.Column("evaluation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("session_id"),
        sa.CheckConstraint(
            "status IN ('active', 'completed', 'expired', 'cancelled')",
            name="ck_learning_sessions_status_valid",
        ),
        sa.CheckConstraint(
            "evaluation_count >= 0",
            name="ck_learning_sessions_evaluation_count_nonnegative",
        ),
        sa.CheckConstraint(
            "review_window_minutes >= 1",
            name="ck_learning_sessions_review_window_minutes_positive",
        ),
    )
    op.create_index("idx_learning_sessions_user_status", "learning_sessions", ["user_id", "status"], unique=False)
    op.create_index("idx_learning_sessions_user_created", "learning_sessions", ["user_id", "created_at"], unique=False)
    op.create_index("idx_learning_sessions_expires_at", "learning_sessions", ["expires_at"], unique=False)

    op.create_table(
        "learning_session_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("learner_response", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=False),
        sa.Column("improvement_score", sa.Float(), nullable=False),
        sa.Column("feedback_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["learning_sessions.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "improvement_score >= 0 AND improvement_score <= 1",
            name="ck_learning_session_attempts_improvement_score_range",
        ),
    )
    op.create_index(
        "idx_learning_session_attempts_session",
        "learning_session_attempts",
        ["session_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_learning_session_attempts_user",
        "learning_session_attempts",
        ["user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_learning_session_attempts_user", table_name="learning_session_attempts")
    op.drop_index("idx_learning_session_attempts_session", table_name="learning_session_attempts")
    op.drop_table("learning_session_attempts")

    op.drop_index("idx_learning_sessions_expires_at", table_name="learning_sessions")
    op.drop_index("idx_learning_sessions_user_created", table_name="learning_sessions")
    op.drop_index("idx_learning_sessions_user_status", table_name="learning_sessions")
    op.drop_table("learning_sessions")
