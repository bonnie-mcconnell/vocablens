"""extend canonical state metrics

Revision ID: 20260321_0012
Revises: 20260321_0011
Create Date: 2026-03-21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260321_0012"
down_revision = "20260321_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_learning_states") as batch_op:
        batch_op.add_column(sa.Column("accuracy_rate", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("response_speed_seconds", sa.Float(), nullable=False, server_default="0"))

    with op.batch_alter_table("user_engagement_states") as batch_op:
        batch_op.add_column(sa.Column("interaction_stats", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    with op.batch_alter_table("user_engagement_states") as batch_op:
        batch_op.drop_column("interaction_stats")

    with op.batch_alter_table("user_learning_states") as batch_op:
        batch_op.drop_column("response_speed_seconds")
        batch_op.drop_column("accuracy_rate")
