from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import UserORM


ROOT = Path(__file__).resolve().parents[1]


def _require_postgres_tests() -> bool:
    return os.getenv("VOCABLENS_REQUIRE_POSTGRES_TESTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class PostgresHarness:
    database_url: str
    engine: object
    session_factory: async_sessionmaker[AsyncSession]


def postgres_root_url() -> str:
    database_url = os.getenv("VOCABLENS_TEST_DATABASE_URL", "").strip()
    if not database_url:
        if _require_postgres_tests():
            raise RuntimeError("VOCABLENS_TEST_DATABASE_URL is required when VOCABLENS_REQUIRE_POSTGRES_TESTS is enabled.")
        pytest.skip("Set VOCABLENS_TEST_DATABASE_URL to run Postgres concurrency tests.")
    return database_url


def alembic_config(database_url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def _admin_connection(root_url: str):
    url = make_url(root_url)
    admin_database = os.getenv("VOCABLENS_TEST_DATABASE_ADMIN_DB", "postgres")
    return await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database=admin_database,
    )


async def _create_database(root_url: str, database_name: str) -> None:
    connection = await _admin_connection(root_url)
    try:
        await connection.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await connection.close()


async def _drop_database(root_url: str, database_name: str) -> None:
    connection = await _admin_connection(root_url)
    try:
        await connection.execute(
            "SELECT pg_terminate_backend(pid) "
            "FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await connection.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await connection.close()


@contextmanager
def postgres_harness():
    require_postgres_tests = _require_postgres_tests()
    root_url = postgres_root_url()
    database_name = f"vocablens_test_{uuid4().hex}"
    database_url = str(make_url(root_url).set(database=database_name))
    try:
        run_async(_create_database(root_url, database_name))
    except (asyncpg.PostgresError, OSError) as exc:
        if require_postgres_tests:
            raise RuntimeError(f"Postgres test database unavailable: {exc}") from exc
        pytest.skip(f"Postgres test database unavailable: {exc}")
    try:
        command.upgrade(alembic_config(database_url), "head")
        engine = create_async_engine(database_url, future=True)
        session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        yield PostgresHarness(
            database_url=database_url,
            engine=engine,
            session_factory=session_factory,
        )
    finally:
        if "engine" in locals():
            run_async(engine.dispose())
        run_async(_drop_database(root_url, database_name))


async def seed_user(session_factory: async_sessionmaker[AsyncSession], *, user_id: int) -> None:
    async with session_factory() as session:
        session.add(
            UserORM(
                id=user_id,
                email=f"user{user_id}@example.com",
                password_hash="hashed-password",
                created_at=utc_now(),
            )
        )
        await session.commit()
