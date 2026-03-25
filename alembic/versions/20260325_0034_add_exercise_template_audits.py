"""add exercise template audits

Revision ID: 20260325_0034
Revises: 20260325_0033
Create Date: 2026-03-25 21:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260325_0034"
down_revision = "20260325_0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exercise_template_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_key", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("changed_by", sa.String(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=False),
        sa.Column("previous_config", sa.JSON(), nullable=False),
        sa.Column("new_config", sa.JSON(), nullable=False),
        sa.Column("fixture_report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["template_key"], ["exercise_templates.template_key"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_exercise_template_audits_template",
        "exercise_template_audits",
        ["template_key", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_exercise_template_audits_action",
        "exercise_template_audits",
        ["action", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_exercise_template_audits_action", table_name="exercise_template_audits")
    op.drop_index("idx_exercise_template_audits_template", table_name="exercise_template_audits")
    op.drop_table("exercise_template_audits")
