from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.domain.models import UserMutationQueueItem
from vocablens.infrastructure.db.models import UserMutationQueueORM, UserQueueSeqORM


def _map_row(row: UserMutationQueueORM) -> UserMutationQueueItem:
    payload = cast(dict[str, Any], row.payload or {})
    return UserMutationQueueItem(
        id=int(cast(Any, row.id)),
        user_id=int(cast(Any, row.user_id)),
        seq=int(cast(Any, row.seq)),
        idempotency_key=str(cast(Any, row.idempotency_key)),
        payload=dict(payload),
        created_at=cast(Any, row.created_at),
    )


class PostgresUserMutationQueueRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def count(self, user_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(UserMutationQueueORM).where(UserMutationQueueORM.user_id == user_id)
        )
        return int(result.scalar_one())

    async def insert(self, *, user_id: int, idempotency_key: str, payload: dict) -> UserMutationQueueItem:
        next_seq = await self.next_seq(user_id)
        row = UserMutationQueueORM(
            user_id=user_id,
            seq=next_seq,
            idempotency_key=idempotency_key,
            payload=payload,
            created_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return _map_row(row)

    async def insert_with_seq(
        self,
        *,
        user_id: int,
        seq: int,
        idempotency_key: str,
        payload: dict,
    ) -> UserMutationQueueItem:
        row = UserMutationQueueORM(
            user_id=user_id,
            seq=int(seq),
            idempotency_key=idempotency_key,
            payload=payload,
            created_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return _map_row(row)

    async def next_seq(self, user_id: int) -> int:
        await self.session.execute(
            text(
                """
                INSERT INTO user_queue_seq(user_id, next_seq, last_applied_seq, updated_at)
                VALUES (:user_id, 1, 0, NOW())
                ON CONFLICT (user_id) DO NOTHING
                """
            ),
            {"user_id": int(user_id)},
        )
        result = await self.session.execute(
            text(
                """
                UPDATE user_queue_seq
                SET next_seq = next_seq + 1,
                    updated_at = NOW()
                WHERE user_id = :user_id
                RETURNING next_seq - 1 AS allocated_seq
                """
            ),
            {"user_id": int(user_id)},
        )
        return int(result.scalar_one())

    async def get_last_applied_seq(self, user_id: int) -> int:
        await self.session.execute(
            text(
                """
                INSERT INTO user_queue_seq(user_id, next_seq, last_applied_seq, updated_at)
                VALUES (:user_id, 1, 0, NOW())
                ON CONFLICT (user_id) DO NOTHING
                """
            ),
            {"user_id": int(user_id)},
        )
        result = await self.session.execute(
            select(UserQueueSeqORM.last_applied_seq).where(UserQueueSeqORM.user_id == int(user_id))
        )
        return int(result.scalar_one())

    async def set_last_applied_seq(self, *, user_id: int, seq: int) -> None:
        await self.session.execute(
            text(
                """
                INSERT INTO user_queue_seq(user_id, next_seq, last_applied_seq, updated_at)
                VALUES (:user_id, 1, 0, NOW())
                ON CONFLICT (user_id) DO NOTHING
                """
            ),
            {"user_id": int(user_id)},
        )
        await self.session.execute(
            update(UserQueueSeqORM)
            .where(UserQueueSeqORM.user_id == int(user_id))
            .values(last_applied_seq=int(seq), updated_at=utc_now())
        )

    async def has_seq(self, *, user_id: int, seq: int) -> bool:
        result = await self.session.execute(
            select(UserMutationQueueORM.id)
            .where(UserMutationQueueORM.user_id == int(user_id))
            .where(UserMutationQueueORM.seq == int(seq))
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def is_overloaded(self, *, user_id: int, depth_threshold: int, sustained_seconds: int) -> bool:
        depth = await self.count(int(user_id))
        if depth <= int(depth_threshold):
            return False
        oldest_result = await self.session.execute(
            select(func.min(UserMutationQueueORM.created_at)).where(UserMutationQueueORM.user_id == int(user_id))
        )
        oldest_created = oldest_result.scalar_one_or_none()
        if oldest_created is None:
            return False
        return oldest_created <= (utc_now() - timedelta(seconds=int(sustained_seconds)))

    async def coalesce_latest_xp_delta(self, *, user_id: int, xp_delta: int) -> bool:
        latest_result = await self.session.execute(
            select(UserMutationQueueORM)
            .where(UserMutationQueueORM.user_id == int(user_id))
            .order_by(UserMutationQueueORM.seq.desc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = latest_result.scalar_one_or_none()
        if row is None:
            return False
        payload = dict(cast(dict[str, Any], row.payload or {}))
        if "xp_delta" not in payload:
            return False
        payload["xp_delta"] = int(payload.get("xp_delta", 0)) + int(xp_delta)
        await self.session.execute(
            update(UserMutationQueueORM)
            .where(UserMutationQueueORM.id == int(cast(Any, row.id)))
            .values(payload=payload)
        )
        return True

    async def claim_batch(self, *, user_id: int, limit: int) -> list[UserMutationQueueItem]:
        result = await self.session.execute(
            select(UserMutationQueueORM)
            .where(UserMutationQueueORM.user_id == user_id)
            .order_by(UserMutationQueueORM.seq.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return [_map_row(row) for row in result.scalars().all()]

    async def delete_ids(self, ids: list[int]) -> None:
        if not ids:
            return
        await self.session.execute(
            delete(UserMutationQueueORM).where(UserMutationQueueORM.id.in_(ids))
        )
