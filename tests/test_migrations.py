from pathlib import Path
import shutil

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / ".migration_test_artifacts"


def _make_config(db_path: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    return config


def test_upgrade_downgrade_upgrade_round_trip():
    if ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS, ignore_errors=True)
    ARTIFACTS.mkdir(exist_ok=True)
    db_path = ARTIFACTS / "migrations.sqlite"
    config = _make_config(db_path)

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)

    tables = set(inspector.get_table_names())
    assert {"usage_logs", "subscriptions", "mistake_patterns", "user_profiles"} <= tables

    usage_indexes = {idx["name"] for idx in inspector.get_indexes("usage_logs")}
    assert "idx_usage_user_day" in usage_indexes
    assert "idx_usage_endpoint" in usage_indexes

    subscription_indexes = {idx["name"] for idx in inspector.get_indexes("subscriptions")}
    assert "idx_subscription_user" in subscription_indexes
    assert "idx_subscription_renewed_at" in subscription_indexes

    mistake_indexes = {idx["name"] for idx in inspector.get_indexes("mistake_patterns")}
    assert "idx_mistake_user_category" in mistake_indexes
    assert "idx_mistake_user_last_seen" in mistake_indexes

    profile_indexes = {idx["name"] for idx in inspector.get_indexes("user_profiles")}
    assert "idx_user_profile_user" in profile_indexes
    assert "idx_user_profile_updated_at" in profile_indexes
    assert "idx_user_profile_last_active_at" in profile_indexes
    assert "idx_user_profile_drop_off_risk" in profile_indexes

    profile_columns = {col["name"] for col in inspector.get_columns("user_profiles")}
    assert {"last_active_at", "session_frequency", "current_streak", "longest_streak", "drop_off_risk"} <= profile_columns

    fks = inspector.get_foreign_keys("usage_logs")
    assert any(fk["referred_table"] == "users" for fk in fks)
    fks = inspector.get_foreign_keys("subscriptions")
    assert any(fk["referred_table"] == "users" for fk in fks)
    fks = inspector.get_foreign_keys("mistake_patterns")
    assert any(fk["referred_table"] == "users" for fk in fks)
    fks = inspector.get_foreign_keys("user_profiles")
    assert any(fk["referred_table"] == "users" for fk in fks)

    command.downgrade(config, "20260317_0001")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "usage_logs" not in tables
    assert "subscriptions" not in tables
    assert "mistake_patterns" not in tables
    assert "user_profiles" not in tables

    command.upgrade(config, "head")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"usage_logs", "subscriptions", "mistake_patterns", "user_profiles"} <= tables
    engine.dispose()

    shutil.rmtree(ARTIFACTS, ignore_errors=True)
