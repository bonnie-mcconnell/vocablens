from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.core.time import utc_now
from vocablens.domain.models import MutationLedgerEntry
from vocablens.infrastructure.db.models import MutationLedgerORM


def _map_row(row: MutationLedgerORM) -> MutationLedgerEntry:
    return MutationLedgerEntry(
        user_id=int(row.user_id),
        idempotency_key=str(row.idempotency_key),
        source=str(row.source),
        reference_id=row.reference_id,
        result_code=row.result_code,
        result_hash=row.result_hash,
        response_etag=row.response_etag,
        created_at=row.created_at,
    )


class PostgresMutationLedgerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: int, idempotency_key: str) -> MutationLedgerEntry | None:
        result = await self.session.execute(
            select(MutationLedgerORM)
            .where(MutationLedgerORM.user_id == user_id)
            .where(MutationLedgerORM.idempotency_key == idempotency_key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return _map_row(row)

    async def insert(
        self,
        *,
        user_id: int,
        idempotency_key: str,
        source: str,
        reference_id: str | None,
        result_code: int,
        result_hash: str | None = None,
        response_etag: str | None = None,
    ) -> MutationLedgerEntry:
        row = MutationLedgerORM(
            user_id=user_id,
            idempotency_key=idempotency_key,
            source=source,
            reference_id=reference_id,
            result_code=result_code,
            result_hash=result_hash,
            response_etag=response_etag,
            created_at=utc_now(),
        )
        self.session.add(row)
        await self.session.flush()
        return _map_row(row)
