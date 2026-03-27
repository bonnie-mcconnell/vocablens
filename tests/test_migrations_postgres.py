from alembic import command
from sqlalchemy import inspect

from tests.conftest import run_async
from tests.postgres_harness import alembic_config, postgres_harness


def _collect_schema_snapshot(engine) -> dict[str, object]:
    async def _collect() -> dict[str, object]:
        async with engine.begin() as conn:
            def _sync_collect(sync_conn):
                schema_inspector = inspect(sync_conn)
                tables = set(schema_inspector.get_table_names())
                usage_indexes = {idx["name"] for idx in schema_inspector.get_indexes("usage_logs")}
                subscription_indexes = {
                    idx["name"] for idx in schema_inspector.get_indexes("subscriptions")
                }
                usage_fks = schema_inspector.get_foreign_keys("usage_logs")
                return {
                    "tables": tables,
                    "usage_indexes": usage_indexes,
                    "subscription_indexes": subscription_indexes,
                    "usage_fks": usage_fks,
                }

            return await conn.run_sync(_sync_collect)

    return run_async(_collect())


def test_postgres_migration_round_trip_head_schema():
    with postgres_harness() as harness:
        config = alembic_config(harness.database_url)

        # Validate downgrade -> upgrade works against the production database engine.
        command.downgrade(config, "20260317_0001")
        command.upgrade(config, "head")

        # A second head upgrade should be a no-op and remain stable.
        command.upgrade(config, "head")

        snapshot = _collect_schema_snapshot(harness.engine)
        tables = snapshot["tables"]

        assert {"usage_logs", "subscriptions", "mistake_patterns", "user_profiles"} <= tables
        assert {"learning_sessions", "learning_session_attempts"} <= tables
        assert "experiment_assignments" in tables

        usage_indexes = snapshot["usage_indexes"]
        assert "idx_usage_user_day" in usage_indexes
        assert "idx_usage_endpoint" in usage_indexes

        subscription_indexes = snapshot["subscription_indexes"]
        assert "idx_subscription_user" in subscription_indexes
        assert "idx_subscription_renewed_at" in subscription_indexes

        usage_fks = snapshot["usage_fks"]
        assert any(fk["referred_table"] == "users" for fk in usage_fks)
