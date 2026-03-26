from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy import func, select

from tests.conftest import run_async
from tests.postgres_harness import postgres_harness, seed_user
from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import (
    DailyMissionORM,
    DecisionTraceORM,
    RewardChestORM,
    UserEngagementStateORM,
    UserProgressStateORM,
)
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.services.daily_loop_service import DailyLoopService


class StubLearningEngine:
    async def get_next_lesson(self, user_id: int):
        return SimpleNamespace(
            action="practice_grammar",
            target="grammar",
            reason="Grammar weak",
            lesson_difficulty="medium",
            skill_focus="grammar",
        )


class StubGamificationService:
    async def summary(self, user_id: int):
        return SimpleNamespace(
            current_streak=4,
            xp=120,
            badges=[SimpleNamespace(label="Accuracy Ace")],
        )


class StubNotificationEngine:
    async def decide(self, user_id: int, assessment):
        return SimpleNamespace(
            should_send=True,
            channel="push",
            send_at=utc_now().replace(hour=18, minute=0, second=0, microsecond=0),
            reason="retention action selected",
        )


class StubRetentionEngine:
    async def assess_user(self, user_id: int):
        return SimpleNamespace(
            current_streak=4,
            drop_off_risk=0.2,
            state="active",
            suggested_actions=[],
        )

    async def record_activity(self, user_id: int, occurred_at=None):
        return None


class NullDailyLoopHealthSignalService:
    async def evaluate_scope(self, scope_key: str = "global"):
        return {"scope_key": scope_key}


async def _load_loop_state(session_factory, *, user_id: int) -> dict[str, object]:
    mission_date = utc_now().date().isoformat()
    async with session_factory() as session:
        missions = (
            await session.execute(
                select(DailyMissionORM)
                .where(
                    DailyMissionORM.user_id == user_id,
                    DailyMissionORM.mission_date == mission_date,
                )
                .order_by(DailyMissionORM.id.asc())
            )
        ).scalars().all()
        mission = missions[0] if missions else None
        chests = []
        if mission is not None:
            chests = (
                await session.execute(
                    select(RewardChestORM)
                    .where(RewardChestORM.mission_id == mission.id)
                    .order_by(RewardChestORM.id.asc())
                )
            ).scalars().all()
        engagement = (
            await session.execute(
                select(UserEngagementStateORM).where(UserEngagementStateORM.user_id == user_id)
            )
        ).scalar_one_or_none()
        progress = (
            await session.execute(
                select(UserProgressStateORM).where(UserProgressStateORM.user_id == user_id)
            )
        ).scalar_one_or_none()
        mission_trace_count = await session.scalar(
            select(func.count())
            .select_from(DecisionTraceORM)
            .where(
                DecisionTraceORM.user_id == user_id,
                DecisionTraceORM.trace_type == "daily_mission_generation",
            )
        )
        reward_trace_count = await session.scalar(
            select(func.count())
            .select_from(DecisionTraceORM)
            .where(
                DecisionTraceORM.user_id == user_id,
                DecisionTraceORM.trace_type == "reward_chest_resolution",
            )
        )
        claim_trace_count = await session.scalar(
            select(func.count())
            .select_from(DecisionTraceORM)
            .where(
                DecisionTraceORM.user_id == user_id,
                DecisionTraceORM.source == "daily_loop_service.claim_reward_chest",
            )
        )
        await session.commit()
    return {
        "missions": list(missions),
        "mission": mission,
        "chests": list(chests),
        "chest": chests[0] if chests else None,
        "engagement": engagement,
        "progress": progress,
        "mission_trace_count": int(mission_trace_count or 0),
        "reward_trace_count": int(reward_trace_count or 0),
        "claim_trace_count": int(claim_trace_count or 0),
    }


async def _build_many(service: DailyLoopService, *, user_id: int, worker_count: int):
    return await asyncio.gather(*[service.build_daily_loop(user_id) for _ in range(worker_count)])


async def _complete_many(service: DailyLoopService, *, user_id: int, worker_count: int):
    return await asyncio.gather(*[service.complete_daily_mission(user_id) for _ in range(worker_count)])


async def _claim_many(service: DailyLoopService, *, user_id: int, worker_count: int):
    return await asyncio.gather(*[service.claim_reward_chest(user_id) for _ in range(worker_count)])


def _service(session_factory) -> DailyLoopService:
    return DailyLoopService(
        UnitOfWorkFactory(session_factory),
        StubLearningEngine(),
        StubGamificationService(),
        StubNotificationEngine(),
        StubRetentionEngine(),
        daily_loop_health_signal_service=NullDailyLoopHealthSignalService(),
    )


def test_daily_loop_issue_concurrency_persists_single_mission_and_chest():
    with postgres_harness() as harness:
        run_async(seed_user(harness.session_factory, user_id=301))
        service = _service(harness.session_factory)

        plans = run_async(_build_many(service, user_id=301, worker_count=10))
        state = run_async(_load_loop_state(harness.session_factory, user_id=301))

        assert len({plan.date for plan in plans}) == 1
        assert len(state["missions"]) == 1
        assert len(state["chests"]) == 1
        assert state["mission"].status == "issued"
        assert state["chest"].status == "locked"
        assert state["mission_trace_count"] == 1


def test_daily_loop_completion_concurrency_applies_progress_once():
    with postgres_harness() as harness:
        run_async(seed_user(harness.session_factory, user_id=302))
        service = _service(harness.session_factory)

        run_async(service.build_daily_loop(302))
        completions = run_async(_complete_many(service, user_id=302, worker_count=6))
        state = run_async(_load_loop_state(harness.session_factory, user_id=302))

        assert all(item.completed is True for item in completions)
        assert state["mission"].status == "completed"
        assert state["chest"].status == "unlocked"
        assert float(state["engagement"].momentum_score or 0.0) == 0.2
        assert int(state["progress"].xp or 0) == 25
        assert int(state["progress"].level or 1) == 1
        assert state["reward_trace_count"] == 1


def test_daily_loop_claim_concurrency_claims_single_chest_once():
    with postgres_harness() as harness:
        run_async(seed_user(harness.session_factory, user_id=303))
        service = _service(harness.session_factory)

        run_async(service.build_daily_loop(303))
        run_async(service.complete_daily_mission(303))
        claims = run_async(_claim_many(service, user_id=303, worker_count=5))
        state = run_async(_load_loop_state(harness.session_factory, user_id=303))

        first_claims = [item for item in claims if item.already_claimed is False]
        repeat_claims = [item for item in claims if item.already_claimed is True]

        assert len(first_claims) == 1
        assert len(repeat_claims) == 4
        assert state["chest"].status == "claimed"
        assert state["reward_trace_count"] == 2
        assert state["claim_trace_count"] == 1
