"""harden learning sessions

Revision ID: 20260324_0022
Revises: 20260324_0021
Create Date: 2026-03-24 14:15:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260324_0022"
down_revision = "20260324_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("learning_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("contract_version", sa.String(), nullable=False, server_default="v2"),
        )
        batch_op.add_column(
            sa.Column("max_response_words", sa.Integer(), nullable=False, server_default=sa.text("12")),
        )
        batch_op.create_check_constraint(
            "ck_learning_sessions_max_response_words_positive",
            "max_response_words >= 1",
        )

    with op.batch_alter_table("learning_session_attempts") as batch_op:
        batch_op.add_column(
            sa.Column("submission_id", sa.String(), nullable=False, server_default="legacy_attempt"),
        )
        batch_op.add_column(
            sa.Column("response_word_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
        batch_op.add_column(
            sa.Column("response_char_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
        batch_op.add_column(
            sa.Column("validation_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )
        batch_op.create_check_constraint(
            "ck_learning_session_attempts_word_count_nonnegative",
            "response_word_count >= 0",
        )
        batch_op.create_check_constraint(
            "ck_learning_session_attempts_char_count_nonnegative",
            "response_char_count >= 0",
        )
        batch_op.create_unique_constraint(
            "uq_learning_session_attempts_submission",
            ["session_id", "submission_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("learning_session_attempts") as batch_op:
        batch_op.drop_constraint("uq_learning_session_attempts_submission", type_="unique")
        batch_op.drop_constraint("ck_learning_session_attempts_char_count_nonnegative", type_="check")
        batch_op.drop_constraint("ck_learning_session_attempts_word_count_nonnegative", type_="check")
        batch_op.drop_column("validation_payload")
        batch_op.drop_column("response_char_count")
        batch_op.drop_column("response_word_count")
        batch_op.drop_column("submission_id")

    with op.batch_alter_table("learning_sessions") as batch_op:
        batch_op.drop_constraint("ck_learning_sessions_max_response_words_positive", type_="check")
        batch_op.drop_column("max_response_words")
        batch_op.drop_column("contract_version")
