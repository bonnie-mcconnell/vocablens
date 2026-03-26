from __future__ import annotations

import asyncio
from types import SimpleNamespace

from sqlalchemy import func, select

from tests.conftest import run_async
from tests.postgres_harness import postgres_harness, seed_user
from vocablens.infrastructure.db.models import (
    DecisionTraceORM,
    EventORM,
    LearningSessionAttemptORM,
    LearningSessionORM,
)
from vocablens.infrastructure.unit_of_work import UnitOfWorkFactory
from vocablens.services.session_engine import SessionEngine


class StubLearningEngine:
    async def get_next_lesson(self, user_id: int):
        return SimpleNamespace(
            action="practice_grammar",
            target="grammar",
            reason="Grammar skill below threshold",
            skill_focus="grammar",
            goal_label="Fix one grammar pattern cleanly",
            review_window_minutes=15,
        )

    async def apply_session_result(self, user_id: int, session_result, *, source: str, uow=None, reference_id: str | None = None):
        return SimpleNamespace(
            reviewed_count=1,
            learned_count=0,
            weak_areas=session_result.weak_areas,
            updated_item_ids=[],
            interaction_stats={"lessons_completed": 1, "reviews_completed": 1},
        )


class StubWowEngine:
    async def score_session(
        self,
        user_id: int,
        *,
        tutor_mode: bool,
        correction_feedback_count: int,
        new_words_count: int,
        grammar_mistake_count: int,
        session_turn_count: int,
        reply_length: int,
    ):
        return SimpleNamespace(score=0.78)


class StubGamificationService:
    async def summary(self, user_id: int):
        return SimpleNamespace(xp=120, badges=[])


async def _load_session_state(session_factory, *, session_id: str) -> dict[str, object]:
    async with session_factory() as session:
        session_row = (
            await session.execute(
                select(LearningSessionORM).where(LearningSessionORM.session_id == session_id)
            )
        ).scalar_one()
        attempt_rows = (
            await session.execute(
                select(LearningSessionAttemptORM)
                .where(LearningSessionAttemptORM.session_id == session_id)
                .order_by(LearningSessionAttemptORM.id.asc())
            )
        ).scalars().all()
        event_count = await session.scalar(
            select(func.count())
            .select_from(EventORM)
            .where(EventORM.payload["session_id"].as_string() == session_id)
        )
        trace_count = await session.scalar(
            select(func.count())
            .select_from(DecisionTraceORM)
            .where(
                DecisionTraceORM.reference_id == session_id,
                DecisionTraceORM.trace_type == "session_evaluation",
            )
        )
        await session.commit()
    return {
        "session": session_row,
        "attempts": list(attempt_rows),
        "event_count": int(event_count or 0),
        "trace_count": int(trace_count or 0),
    }


async def _evaluate_same_submission_many(
    engine: SessionEngine,
    *,
    user_id: int,
    session_id: str,
    contract_version: str,
    submission_id: str,
    worker_count: int,
):
    async def _run_one():
        feedback = await engine.evaluate_session(
            user_id,
            session_id,
            "I goed there yesterday",
            submission_id=submission_id,
            contract_version=contract_version,
        )
        return feedback.corrected_response

    return await asyncio.gather(*[_run_one() for _ in range(worker_count)])


async def _evaluate_distinct_submissions_many(
    engine: SessionEngine,
    *,
    user_id: int,
    session_id: str,
    contract_version: str,
    worker_count: int,
):
    async def _run_one(index: int):
        try:
            feedback = await engine.evaluate_session(
                user_id,
                session_id,
                "I goed there yesterday",
                submission_id=f"submit_distinct_{index:02d}",
                contract_version=contract_version,
            )
            return {"status": "ok", "corrected_response": feedback.corrected_response}
        except Exception as exc:
            return {"status": "error", "error_type": type(exc).__name__, "message": str(exc)}

    return await asyncio.gather(*[_run_one(index) for index in range(worker_count)])


def test_session_same_submission_concurrency_persists_single_attempt():
    with postgres_harness() as harness:
        run_async(seed_user(harness.session_factory, user_id=201))
        engine = SessionEngine(
            UnitOfWorkFactory(harness.session_factory),
            StubLearningEngine(),
            StubWowEngine(),
            StubGamificationService(),
        )

        started = run_async(engine.start_session(201))
        results = run_async(
            _evaluate_same_submission_many(
                engine,
                user_id=201,
                session_id=started["session_id"],
                contract_version=started["contract_version"],
                submission_id="submit_same_concurrent",
                worker_count=8,
            )
        )
        state = run_async(
            _load_session_state(
                harness.session_factory,
                session_id=started["session_id"],
            )
        )

        assert set(results) == {"I went there yesterday."}
        assert state["session"].status == "completed"
        assert state["session"].evaluation_count == 1
        assert len(state["attempts"]) == 1
        assert state["attempts"][0].submission_id == "submit_same_concurrent"
        assert state["event_count"] == 2
        assert state["trace_count"] == 1


def test_session_distinct_submission_concurrency_keeps_single_winning_attempt():
    with postgres_harness() as harness:
        run_async(seed_user(harness.session_factory, user_id=202))
        engine = SessionEngine(
            UnitOfWorkFactory(harness.session_factory),
            StubLearningEngine(),
            StubWowEngine(),
            StubGamificationService(),
        )

        started = run_async(engine.start_session(202))
        results = run_async(
            _evaluate_distinct_submissions_many(
                engine,
                user_id=202,
                session_id=started["session_id"],
                contract_version=started["contract_version"],
                worker_count=6,
            )
        )
        state = run_async(
            _load_session_state(
                harness.session_factory,
                session_id=started["session_id"],
            )
        )

        ok_results = [item for item in results if item["status"] == "ok"]
        error_results = [item for item in results if item["status"] == "error"]

        assert len(ok_results) == 1
        assert ok_results[0]["corrected_response"] == "I went there yesterday."
        assert len(error_results) == 5
        assert {item["error_type"] for item in error_results} == {"ConflictError"}
        assert all("completed" in item["message"].lower() for item in error_results)
        assert state["session"].status == "completed"
        assert state["session"].evaluation_count == 1
        assert len(state["attempts"]) == 1
        assert state["event_count"] == 2
        assert state["trace_count"] == 1
