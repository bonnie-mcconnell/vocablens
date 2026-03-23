from __future__ import annotations

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.domain.models import LearningSession, LearningSessionAttempt
from vocablens.infrastructure.db.models import LearningSessionAttemptORM, LearningSessionORM


def _map_session(row: LearningSessionORM) -> LearningSession:
    return LearningSession(
        session_id=row.session_id,
        user_id=row.user_id,
        status=str(row.status),
        duration_seconds=int(row.duration_seconds),
        mode=str(row.mode),
        weak_area=str(row.weak_area),
        lesson_target=row.lesson_target,
        goal_label=str(row.goal_label),
        success_criteria=str(row.success_criteria),
        review_window_minutes=int(row.review_window_minutes),
        session_payload=dict(row.session_payload or {}),
        created_at=row.created_at,
        expires_at=row.expires_at,
        completed_at=row.completed_at,
        last_evaluated_at=row.last_evaluated_at,
        evaluation_count=int(row.evaluation_count or 0),
    )


def _map_attempt(row: LearningSessionAttemptORM) -> LearningSessionAttempt:
    return LearningSessionAttempt(
        id=int(row.id),
        session_id=str(row.session_id),
        user_id=int(row.user_id),
        learner_response=str(row.learner_response),
        is_correct=bool(row.is_correct),
        improvement_score=float(row.improvement_score),
        feedback_payload=dict(row.feedback_payload or {}),
        created_at=row.created_at,
    )


class PostgresLearningSessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        session_id: str,
        user_id: int,
        duration_seconds: int,
        mode: str,
        weak_area: str,
        lesson_target: str | None,
        goal_label: str,
        success_criteria: str,
        review_window_minutes: int,
        session_payload: dict,
        expires_at,
    ) -> LearningSession:
        await self.session.execute(
            insert(LearningSessionORM).values(
                session_id=session_id,
                user_id=user_id,
                status="active",
                duration_seconds=duration_seconds,
                mode=mode,
                weak_area=weak_area,
                lesson_target=lesson_target,
                goal_label=goal_label,
                success_criteria=success_criteria,
                review_window_minutes=review_window_minutes,
                session_payload=dict(session_payload),
                expires_at=expires_at,
            )
        )
        result = await self.session.execute(
            select(LearningSessionORM).where(LearningSessionORM.session_id == session_id)
        )
        return _map_session(result.scalar_one())

    async def get(self, *, user_id: int, session_id: str) -> LearningSession | None:
        result = await self.session.execute(
            select(LearningSessionORM).where(
                LearningSessionORM.user_id == user_id,
                LearningSessionORM.session_id == session_id,
            )
        )
        row = result.scalar_one_or_none()
        return _map_session(row) if row is not None else None

    async def get_by_session_id(self, session_id: str) -> LearningSession | None:
        result = await self.session.execute(
            select(LearningSessionORM).where(LearningSessionORM.session_id == session_id)
        )
        row = result.scalar_one_or_none()
        return _map_session(row) if row is not None else None

    async def mark_completed(self, *, user_id: int, session_id: str, completed_at) -> LearningSession:
        await self.session.execute(
            update(LearningSessionORM)
            .where(
                LearningSessionORM.user_id == user_id,
                LearningSessionORM.session_id == session_id,
            )
            .values(
                status="completed",
                completed_at=completed_at,
                last_evaluated_at=completed_at,
                evaluation_count=LearningSessionORM.evaluation_count + 1,
            )
        )
        result = await self.session.execute(
            select(LearningSessionORM).where(
                LearningSessionORM.user_id == user_id,
                LearningSessionORM.session_id == session_id,
            )
        )
        return _map_session(result.scalar_one())

    async def mark_expired(self, *, user_id: int, session_id: str, expired_at) -> LearningSession:
        await self.session.execute(
            update(LearningSessionORM)
            .where(
                LearningSessionORM.user_id == user_id,
                LearningSessionORM.session_id == session_id,
            )
            .values(
                status="expired",
                last_evaluated_at=expired_at,
            )
        )
        result = await self.session.execute(
            select(LearningSessionORM).where(
                LearningSessionORM.user_id == user_id,
                LearningSessionORM.session_id == session_id,
            )
        )
        return _map_session(result.scalar_one())

    async def record_attempt(
        self,
        *,
        session_id: str,
        user_id: int,
        learner_response: str,
        is_correct: bool,
        improvement_score: float,
        feedback_payload: dict,
    ) -> LearningSessionAttempt:
        result = await self.session.execute(
            insert(LearningSessionAttemptORM)
            .values(
                session_id=session_id,
                user_id=user_id,
                learner_response=learner_response,
                is_correct=is_correct,
                improvement_score=improvement_score,
                feedback_payload=dict(feedback_payload),
            )
            .returning(LearningSessionAttemptORM)
        )
        return _map_attempt(result.scalar_one())

    async def list_attempts(self, *, session_id: str) -> list[LearningSessionAttempt]:
        result = await self.session.execute(
            select(LearningSessionAttemptORM)
            .where(LearningSessionAttemptORM.session_id == session_id)
            .order_by(LearningSessionAttemptORM.created_at.asc(), LearningSessionAttemptORM.id.asc())
        )
        return [_map_attempt(row) for row in result.scalars().all()]
