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
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest import run_async
from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import (
    ExperimentAssignmentORM,
    ExperimentExposureORM,
    ExperimentOutcomeAttributionORM,
    ExperimentRegistryORM,
    UserORM,
)
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.services.experiment_attribution_service import ExperimentAttributionService
from vocablens.services.experiment_service import ExperimentContext, ExperimentService


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class PostgresHarness:
    database_url: str
    engine: object
    session_factory: async_sessionmaker[AsyncSession]


class NullExperimentHealthSignalService:
    async def evaluate_experiment(self, experiment_key: str):
        return {"experiment_key": experiment_key}


def _postgres_root_url() -> str:
    database_url = os.getenv("VOCABLENS_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("Set VOCABLENS_TEST_DATABASE_URL to run Postgres concurrency tests.")
    return database_url


def _alembic_config(database_url: str) -> Config:
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
    root_url = _postgres_root_url()
    database_name = f"vocablens_test_{uuid4().hex}"
    database_url = str(make_url(root_url).set(database=database_name))
    try:
        run_async(_create_database(root_url, database_name))
    except (asyncpg.PostgresError, OSError) as exc:
        pytest.skip(f"Postgres test database unavailable: {exc}")
    try:
        command.upgrade(_alembic_config(database_url), "head")
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


async def _seed_user(session_factory: async_sessionmaker[AsyncSession], *, user_id: int) -> None:
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


async def _seed_registry(session_factory: async_sessionmaker[AsyncSession], *, experiment_key: str) -> None:
    async with session_factory() as session:
        session.add(
            ExperimentRegistryORM(
                experiment_key=experiment_key,
                status="active",
                rollout_percentage=100,
                holdout_percentage=0,
                is_killed=False,
                baseline_variant="control",
                description="Postgres concurrency coverage",
                variants=[
                    {"name": "control", "weight": 50},
                    {"name": "annual_anchor", "weight": 50},
                ],
                eligibility={},
                mutually_exclusive_with=[],
                prerequisite_experiments=[],
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        await session.commit()


async def _seed_assignment(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int,
    experiment_key: str,
    variant: str,
) -> None:
    async with session_factory() as session:
        session.add(
            ExperimentAssignmentORM(
                user_id=user_id,
                experiment_key=experiment_key,
                variant=variant,
                assigned_at=utc_now(),
            )
        )
        await session.commit()


async def _seed_exposure(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int,
    experiment_key: str,
    variant: str,
):
    exposed_at = utc_now()
    async with session_factory() as session:
        session.add(
            ExperimentExposureORM(
                user_id=user_id,
                experiment_key=experiment_key,
                variant=variant,
                exposed_at=exposed_at,
            )
        )
        await session.commit()
    return exposed_at


async def _load_state(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int,
    experiment_key: str,
) -> dict[str, object]:
    async with session_factory() as session:
        assignment = (
            await session.execute(
                select(ExperimentAssignmentORM).where(
                    ExperimentAssignmentORM.user_id == user_id,
                    ExperimentAssignmentORM.experiment_key == experiment_key,
                )
            )
        ).scalar_one_or_none()
        exposure = (
            await session.execute(
                select(ExperimentExposureORM).where(
                    ExperimentExposureORM.user_id == user_id,
                    ExperimentExposureORM.experiment_key == experiment_key,
                )
            )
        ).scalar_one_or_none()
        attribution = (
            await session.execute(
                select(ExperimentOutcomeAttributionORM).where(
                    ExperimentOutcomeAttributionORM.user_id == user_id,
                    ExperimentOutcomeAttributionORM.experiment_key == experiment_key,
                )
            )
        ).scalar_one_or_none()
        assignment_count = await session.scalar(
            select(func.count())
            .select_from(ExperimentAssignmentORM)
            .where(
                ExperimentAssignmentORM.user_id == user_id,
                ExperimentAssignmentORM.experiment_key == experiment_key,
            )
        )
        exposure_count = await session.scalar(
            select(func.count())
            .select_from(ExperimentExposureORM)
            .where(
                ExperimentExposureORM.user_id == user_id,
                ExperimentExposureORM.experiment_key == experiment_key,
            )
        )
        attribution_count = await session.scalar(
            select(func.count())
            .select_from(ExperimentOutcomeAttributionORM)
            .where(
                ExperimentOutcomeAttributionORM.user_id == user_id,
                ExperimentOutcomeAttributionORM.experiment_key == experiment_key,
            )
        )
        await session.commit()
    return {
        "assignment": assignment,
        "exposure": exposure,
        "attribution": attribution,
        "assignment_count": int(assignment_count or 0),
        "exposure_count": int(exposure_count or 0),
        "attribution_count": int(attribution_count or 0),
    }


async def _assign_many(
    service: ExperimentService,
    *,
    user_id: int,
    experiment_key: str,
    worker_count: int,
) -> list[str]:
    context = ExperimentContext(
        geography="us",
        subscription_tier="free",
        lifecycle_stage="activating",
        platform="ios",
        surface="paywall",
    )
    return await __import__("asyncio").gather(
        *[
            service.assign(user_id, experiment_key, context=context)
            for _ in range(worker_count)
        ]
    )


async def _seed_attribution_many(
    service: ExperimentAttributionService,
    *,
    user_id: int,
    experiment_key: str,
    variant: str,
    exposed_at,
    worker_count: int,
):
    return await __import__("asyncio").gather(
        *[
            service.ensure_exposure(
                user_id=user_id,
                experiment_key=experiment_key,
                variant=variant,
                exposed_at=exposed_at,
                assignment_reason="rollout",
            )
            for _ in range(worker_count)
        ]
    )


def test_experiment_assignment_concurrency_persists_single_canonical_rows():
    with postgres_harness() as harness:
        run_async(_seed_user(harness.session_factory, user_id=101))
        run_async(_seed_registry(harness.session_factory, experiment_key="paywall_offer"))
        service = ExperimentService(
            UnitOfWorkFactory(harness.session_factory),
            health_signal_service=NullExperimentHealthSignalService(),
        )

        variants = run_async(
            _assign_many(
                service,
                user_id=101,
                experiment_key="paywall_offer",
                worker_count=12,
            )
        )
        state = run_async(
            _load_state(
                harness.session_factory,
                user_id=101,
                experiment_key="paywall_offer",
            )
        )

        assert len(set(variants)) == 1
        assert state["assignment_count"] == 1
        assert state["exposure_count"] == 1
        assert state["attribution_count"] == 1
        assert state["assignment"] is not None
        assert state["exposure"] is not None
        assert state["attribution"] is not None
        assert state["assignment"].variant == state["exposure"].variant
        assert state["attribution"].variant == state["exposure"].variant
        assert state["attribution"].exposed_at == state["exposure"].exposed_at


def test_experiment_assignment_concurrency_backfills_single_exposure_and_attribution():
    with postgres_harness() as harness:
        run_async(_seed_user(harness.session_factory, user_id=102))
        run_async(_seed_registry(harness.session_factory, experiment_key="pricing_test"))
        run_async(
            _seed_assignment(
                harness.session_factory,
                user_id=102,
                experiment_key="pricing_test",
                variant="annual_anchor",
            )
        )
        service = ExperimentService(
            UnitOfWorkFactory(harness.session_factory),
            health_signal_service=NullExperimentHealthSignalService(),
        )

        variants = run_async(
            _assign_many(
                service,
                user_id=102,
                experiment_key="pricing_test",
                worker_count=10,
            )
        )
        state = run_async(
            _load_state(
                harness.session_factory,
                user_id=102,
                experiment_key="pricing_test",
            )
        )

        assert set(variants) == {"annual_anchor"}
        assert state["assignment_count"] == 1
        assert state["exposure_count"] == 1
        assert state["attribution_count"] == 1
        assert state["assignment"].variant == "annual_anchor"
        assert state["exposure"].variant == "annual_anchor"
        assert state["attribution"].variant == "annual_anchor"
        assert state["attribution"].exposed_at == state["exposure"].exposed_at


def test_experiment_attribution_concurrency_seeds_one_window_from_canonical_exposure():
    with postgres_harness() as harness:
        run_async(_seed_user(harness.session_factory, user_id=103))
        exposed_at = run_async(
            _seed_exposure(
                harness.session_factory,
                user_id=103,
                experiment_key="retention_nudges",
                variant="control",
            )
        )
        service = ExperimentAttributionService(UnitOfWorkFactory(harness.session_factory))

        rows = run_async(
            _seed_attribution_many(
                service,
                user_id=103,
                experiment_key="retention_nudges",
                variant="control",
                exposed_at=exposed_at,
                worker_count=8,
            )
        )
        state = run_async(
            _load_state(
                harness.session_factory,
                user_id=103,
                experiment_key="retention_nudges",
            )
        )

        created_count = sum(1 for _, created in rows if created)
        assert created_count == 1
        assert state["assignment_count"] == 0
        assert state["exposure_count"] == 1
        assert state["attribution_count"] == 1
        assert state["attribution"] is not None
        assert state["attribution"].exposed_at == exposed_at
