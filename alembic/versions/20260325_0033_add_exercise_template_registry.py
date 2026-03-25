"""add exercise template registry

Revision ID: 20260325_0033
Revises: 20260325_0032
Create Date: 2026-03-25 21:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime


revision = "20260325_0033"
down_revision = "20260325_0032"
branch_labels = None
depends_on = None
exercise_templates_table = sa.table(
    "exercise_templates",
    sa.column("template_key", sa.String()),
    sa.column("exercise_type", sa.String()),
    sa.column("objective", sa.String()),
    sa.column("difficulty", sa.String()),
    sa.column("status", sa.String()),
    sa.column("prompt_template", sa.Text()),
    sa.column("answer_source", sa.String()),
    sa.column("choice_count", sa.Integer()),
    sa.column("metadata", sa.JSON()),
    sa.column("created_at", sa.DateTime()),
    sa.column("updated_at", sa.DateTime()),
)


def upgrade() -> None:
    seeded_at = datetime(2026, 3, 25, 21, 10, 0)
    op.create_table(
        "exercise_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_key", sa.String(), nullable=False),
        sa.Column("exercise_type", sa.String(), nullable=False),
        sa.Column("objective", sa.String(), nullable=False),
        sa.Column("difficulty", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("prompt_template", sa.Text(), nullable=False),
        sa.Column("answer_source", sa.String(), nullable=False),
        sa.Column("choice_count", sa.Integer(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key", name="uq_exercise_templates_key"),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_exercise_templates_status_valid",
        ),
    )
    op.create_index(
        "idx_exercise_templates_status",
        "exercise_templates",
        ["status", "objective", "difficulty"],
        unique=False,
    )
    op.create_index(
        "idx_exercise_templates_type",
        "exercise_templates",
        ["exercise_type", "status"],
        unique=False,
    )

    op.bulk_insert(
        exercise_templates_table,
        [
            {
                "template_key": "recall_fill_blank_v1",
                "exercise_type": "fill_blank",
                "objective": "recall",
                "difficulty": "medium",
                "status": "active",
                "prompt_template": "Fill the blank with the target word: {target}.",
                "answer_source": "target",
                "choice_count": None,
                "metadata": {},
                "created_at": seeded_at,
                "updated_at": seeded_at,
            },
            {
                "template_key": "discrimination_choice_v1",
                "exercise_type": "multiple_choice",
                "objective": "discrimination",
                "difficulty": "medium",
                "status": "active",
                "prompt_template": "Choose the option that best matches {target}.",
                "answer_source": "target",
                "choice_count": 4,
                "metadata": {},
                "created_at": seeded_at,
                "updated_at": seeded_at,
            },
            {
                "template_key": "correction_fill_blank_v1",
                "exercise_type": "fill_blank",
                "objective": "correction",
                "difficulty": "medium",
                "status": "active",
                "prompt_template": "Repair the sentence by filling the correct form for {target}.",
                "answer_source": "target",
                "choice_count": None,
                "metadata": {},
                "created_at": seeded_at,
                "updated_at": seeded_at,
            },
            {
                "template_key": "reinforcement_choice_v1",
                "exercise_type": "multiple_choice",
                "objective": "reinforcement",
                "difficulty": "medium",
                "status": "active",
                "prompt_template": "Pick the best follow-up for {target}.",
                "answer_source": "target",
                "choice_count": 4,
                "metadata": {},
                "created_at": seeded_at,
                "updated_at": seeded_at,
            },
            {
                "template_key": "production_fill_blank_v1",
                "exercise_type": "fill_blank",
                "objective": "production",
                "difficulty": "medium",
                "status": "active",
                "prompt_template": "Complete the idea using {target} in a short response.",
                "answer_source": "target",
                "choice_count": None,
                "metadata": {},
                "created_at": seeded_at,
                "updated_at": seeded_at,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_exercise_templates_type", table_name="exercise_templates")
    op.drop_index("idx_exercise_templates_status", table_name="exercise_templates")
    op.drop_table("exercise_templates")
