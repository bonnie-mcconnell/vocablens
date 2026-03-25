"""add content quality tables

Revision ID: 20260325_0032
Revises: 20260325_0031
Create Date: 2026-03-25 20:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0032"
down_revision = "20260325_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_quality_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("artifact_type", sa.String(), nullable=False),
        sa.Column("reference_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("violations", sa.JSON(), nullable=False),
        sa.Column("artifact_summary", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('passed', 'rejected')",
            name="ck_content_quality_checks_status_valid",
        ),
    )
    op.create_index(
        "idx_content_quality_checks_source_checked",
        "content_quality_checks",
        ["source", "checked_at"],
        unique=False,
    )
    op.create_index(
        "idx_content_quality_checks_status_checked",
        "content_quality_checks",
        ["status", "checked_at"],
        unique=False,
    )
    op.create_index(
        "idx_content_quality_checks_reference",
        "content_quality_checks",
        ["reference_id", "checked_at"],
        unique=False,
    )

    op.create_table(
        "content_quality_health_states",
        sa.Column("scope_key", sa.String(), nullable=False),
        sa.Column("current_status", sa.String(), nullable=False),
        sa.Column("latest_alert_codes", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("last_evaluated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("scope_key"),
        sa.CheckConstraint(
            "current_status IN ('healthy', 'warning', 'critical')",
            name="ck_content_quality_health_states_status_valid",
        ),
    )
    op.create_index(
        "idx_content_quality_health_states_status",
        "content_quality_health_states",
        ["current_status", "last_evaluated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_content_quality_health_states_status", table_name="content_quality_health_states")
    op.drop_table("content_quality_health_states")
    op.drop_index("idx_content_quality_checks_reference", table_name="content_quality_checks")
    op.drop_index("idx_content_quality_checks_status_checked", table_name="content_quality_checks")
    op.drop_index("idx_content_quality_checks_source_checked", table_name="content_quality_checks")
    op.drop_table("content_quality_checks")
