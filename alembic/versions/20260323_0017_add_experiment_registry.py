"""add experiment registry

Revision ID: 20260323_0017
Revises: 20260323_0016
Create Date: 2026-03-23 14:05:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20260323_0017"
down_revision = "20260323_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_registries",
        sa.Column("experiment_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("rollout_percentage", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("is_killed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("variants", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'archived')",
            name="ck_experiment_registries_status_valid",
        ),
        sa.CheckConstraint(
            "rollout_percentage >= 0 AND rollout_percentage <= 100",
            name="ck_experiment_registries_rollout_percentage_range",
        ),
        sa.PrimaryKeyConstraint("experiment_key"),
    )
    op.create_index(
        "idx_experiment_registries_status",
        "experiment_registries",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_experiment_registries_updated_at",
        "experiment_registries",
        ["updated_at"],
        unique=False,
    )

    registry = sa.table(
        "experiment_registries",
        sa.column("experiment_key", sa.String()),
        sa.column("status", sa.String()),
        sa.column("rollout_percentage", sa.Integer()),
        sa.column("is_killed", sa.Boolean()),
        sa.column("description", sa.Text()),
        sa.column("variants", sa.JSON()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    op.bulk_insert(
        registry,
        [
            {
                "experiment_key": "learning_strategy",
                "status": "active",
                "rollout_percentage": 100,
                "is_killed": False,
                "description": "Controls lesson selection strategy variants.",
                "variants": [{"name": "control", "weight": 100}],
                "created_at": now,
                "updated_at": now,
            },
            {
                "experiment_key": "retention_nudges",
                "status": "active",
                "rollout_percentage": 100,
                "is_killed": False,
                "description": "Controls retention nudge sequencing.",
                "variants": [{"name": "control", "weight": 100}],
                "created_at": now,
                "updated_at": now,
            },
            {
                "experiment_key": "paywall_offer",
                "status": "active",
                "rollout_percentage": 100,
                "is_killed": False,
                "description": "Controls paywall offer composition.",
                "variants": [{"name": "control", "weight": 100}],
                "created_at": now,
                "updated_at": now,
            },
            {
                "experiment_key": "paywall_trigger_timing",
                "status": "active",
                "rollout_percentage": 100,
                "is_killed": False,
                "description": "Controls paywall trigger timing.",
                "variants": [{"name": "control", "weight": 100}],
                "created_at": now,
                "updated_at": now,
            },
            {
                "experiment_key": "paywall_trial_length",
                "status": "active",
                "rollout_percentage": 100,
                "is_killed": False,
                "description": "Controls trial duration copy and rules.",
                "variants": [{"name": "control", "weight": 100}],
                "created_at": now,
                "updated_at": now,
            },
            {
                "experiment_key": "paywall_pricing_messaging",
                "status": "active",
                "rollout_percentage": 100,
                "is_killed": False,
                "description": "Controls pricing anchor messaging.",
                "variants": [{"name": "control", "weight": 100}],
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_experiment_registries_updated_at", table_name="experiment_registries")
    op.drop_index("idx_experiment_registries_status", table_name="experiment_registries")
    op.drop_table("experiment_registries")
