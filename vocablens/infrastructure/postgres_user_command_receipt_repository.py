from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.infrastructure.db.models import UserCommandReceiptORM


class PostgresUserCommandReceiptRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, *, user_id: int, command_id: str, command_seq: int, mode: str) -> None:
        row = await self.session.get(UserCommandReceiptORM, (int(user_id), str(command_id)))
        if row is None:
            self.session.add(
                UserCommandReceiptORM(
                    user_id=int(user_id),
                    command_id=str(command_id),
                    command_seq=int(command_seq),
                    mode=str(mode),
                    created_at=utc_now(),
                )
            )
            await self.session.flush()
            return
        row.command_seq = int(command_seq)
        row.mode = str(mode)
        row.created_at = utc_now()
        await self.session.flush()

    async def get(self, *, user_id: int, command_id: str) -> dict | None:
        result = await self.session.execute(
            select(UserCommandReceiptORM).where(
                UserCommandReceiptORM.user_id == int(user_id),
                UserCommandReceiptORM.command_id == str(command_id),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "user_id": int(row.user_id),
            "command_id": str(row.command_id),
            "command_seq": int(row.command_seq),
            "mode": str(row.mode),
            "created_at": row.created_at,
        }
