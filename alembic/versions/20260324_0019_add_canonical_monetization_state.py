"""add canonical monetization state

Revision ID: 20260324_0019
Revises: 20260324_0018
Create Date: 2026-03-24 11:05:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0019"
down_revision = "20260324_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_monetization_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("current_offer_type", sa.String(), nullable=True),
        sa.Column("last_paywall_type", sa.String(), nullable=True),
        sa.Column("last_paywall_reason", sa.Text(), nullable=True),
        sa.Column("current_strategy", sa.String(), nullable=True),
        sa.Column("current_geography", sa.String(), nullable=True),
        sa.Column("lifecycle_stage", sa.String(), nullable=True),
        sa.Column("paywall_impressions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("paywall_dismissals", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("paywall_acceptances", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("paywall_skips", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("fatigue_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cooldown_until", sa.DateTime(), nullable=True),
        sa.Column("trial_eligible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trial_started_at", sa.DateTime(), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
        sa.Column("trial_offer_days", sa.Integer(), nullable=True),
        sa.Column("conversion_propensity", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_offer_at", sa.DateTime(), nullable=True),
        sa.Column("last_impression_at", sa.DateTime(), nullable=True),
        sa.Column("last_dismissed_at", sa.DateTime(), nullable=True),
        sa.Column("last_accepted_at", sa.DateTime(), nullable=True),
        sa.Column("last_skipped_at", sa.DateTime(), nullable=True),
        sa.Column("last_pricing", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_trigger", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_value_display", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("paywall_impressions >= 0", name="ck_user_monetization_states_impressions_nonnegative"),
        sa.CheckConstraint("paywall_dismissals >= 0", name="ck_user_monetization_states_dismissals_nonnegative"),
        sa.CheckConstraint("paywall_acceptances >= 0", name="ck_user_monetization_states_acceptances_nonnegative"),
        sa.CheckConstraint("paywall_skips >= 0", name="ck_user_monetization_states_skips_nonnegative"),
        sa.CheckConstraint("fatigue_score >= 0", name="ck_user_monetization_states_fatigue_nonnegative"),
        sa.CheckConstraint(
            "conversion_propensity >= 0 AND conversion_propensity <= 1",
            name="ck_user_monetization_states_conversion_propensity_range",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_monetization_states_user_id"),
    )
    op.create_index("idx_user_monetization_states_user", "user_monetization_states", ["user_id"], unique=False)
    op.create_index("idx_user_monetization_states_updated_at", "user_monetization_states", ["updated_at"], unique=False)
    op.create_index(
        "idx_user_monetization_states_cooldown_until",
        "user_monetization_states",
        ["cooldown_until"],
        unique=False,
    )

    op.create_table(
        "monetization_offer_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("offer_type", sa.String(), nullable=True),
        sa.Column("paywall_type", sa.String(), nullable=True),
        sa.Column("strategy", sa.String(), nullable=True),
        sa.Column("geography", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_monetization_offer_events_user", "monetization_offer_events", ["user_id", "created_at"], unique=False)
    op.create_index("idx_monetization_offer_events_type", "monetization_offer_events", ["event_type", "created_at"], unique=False)
    op.create_index("idx_monetization_offer_events_offer", "monetization_offer_events", ["offer_type", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_monetization_offer_events_offer", table_name="monetization_offer_events")
    op.drop_index("idx_monetization_offer_events_type", table_name="monetization_offer_events")
    op.drop_index("idx_monetization_offer_events_user", table_name="monetization_offer_events")
    op.drop_table("monetization_offer_events")
    op.drop_index("idx_user_monetization_states_cooldown_until", table_name="user_monetization_states")
    op.drop_index("idx_user_monetization_states_updated_at", table_name="user_monetization_states")
    op.drop_index("idx_user_monetization_states_user", table_name="user_monetization_states")
    op.drop_table("user_monetization_states")
