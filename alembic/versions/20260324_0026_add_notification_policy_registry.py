"""add notification policy registry

Revision ID: 20260324_0026
Revises: 20260324_0025
Create Date: 2026-03-24 17:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0026"
down_revision = "20260324_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_policy_registries",
        sa.Column("policy_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("is_killed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("policy", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'archived')",
            name="ck_notification_policy_registries_status_valid",
        ),
        sa.PrimaryKeyConstraint("policy_key"),
    )
    op.create_index(
        "idx_notification_policy_registries_status",
        "notification_policy_registries",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_notification_policy_registries_updated_at",
        "notification_policy_registries",
        ["updated_at"],
        unique=False,
    )

    op.create_table(
        "notification_policy_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("policy_key", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("changed_by", sa.String(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=False),
        sa.Column("previous_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("new_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["policy_key"], ["notification_policy_registries.policy_key"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_notification_policy_audits_policy",
        "notification_policy_audits",
        ["policy_key", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_notification_policy_audits_action",
        "notification_policy_audits",
        ["action", "created_at"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO notification_policy_registries
            (policy_key, status, is_killed, description, policy, created_at, updated_at)
        VALUES
            (
                'default',
                'active',
                0,
                'Canonical notification policy for cadence, lifecycle suppression, and recovery windows.',
                '{
                    "cooldown_hours": 4,
                    "default_frequency_limit": 2,
                    "default_preferred_time_of_day": 18,
                    "stage_policies": {
                        "new_user": {"lifecycle_notifications_enabled": true, "suppression_reason": null, "recovery_window_hours": 0},
                        "activating": {"lifecycle_notifications_enabled": true, "suppression_reason": null, "recovery_window_hours": 0},
                        "engaged": {"lifecycle_notifications_enabled": false, "suppression_reason": "engaged stage suppresses proactive lifecycle messaging", "recovery_window_hours": 24},
                        "at_risk": {"lifecycle_notifications_enabled": true, "suppression_reason": null, "recovery_window_hours": 0},
                        "churned": {"lifecycle_notifications_enabled": true, "suppression_reason": null, "recovery_window_hours": 0}
                    },
                    "suppression_overrides": [
                        {"source_context": "lifecycle_service.notification", "stage": "engaged", "lifecycle_notifications_enabled": false, "suppression_reason": "engaged stage suppresses proactive lifecycle messaging", "recovery_window_hours": 24}
                    ]
                }',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            )
        """
    )
    op.execute(
        """
        INSERT INTO notification_policy_audits
            (policy_key, action, changed_by, change_note, previous_config, new_config, created_at)
        VALUES
            (
                'default',
                'created',
                'system_seed',
                'Seeded canonical default notification policy.',
                '{}',
                '{
                    "policy_key": "default",
                    "status": "active",
                    "is_killed": false
                }',
                CURRENT_TIMESTAMP
            )
        """
    )


def downgrade() -> None:
    op.drop_index("idx_notification_policy_audits_action", table_name="notification_policy_audits")
    op.drop_index("idx_notification_policy_audits_policy", table_name="notification_policy_audits")
    op.drop_table("notification_policy_audits")
    op.drop_index("idx_notification_policy_registries_updated_at", table_name="notification_policy_registries")
    op.drop_index("idx_notification_policy_registries_status", table_name="notification_policy_registries")
    op.drop_table("notification_policy_registries")
