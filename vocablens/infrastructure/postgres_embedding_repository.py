import asyncio
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vocablens.infrastructure.db.models import EmbeddingORM


class PostgresEmbeddingRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def store(self, word: str, embedding: List[float]) -> None:
        async with self._session_factory() as session:
            await session.execute(
                insert(EmbeddingORM)
                .values(word=word, embedding=embedding)
                .on_conflict_do_update(
                    index_elements=[EmbeddingORM.word],
                    set_={"embedding": embedding},
                )
            )
            await session.commit()

    async def get(self, word: str) -> Optional[List[float]]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(EmbeddingORM.embedding).where(EmbeddingORM.word == word)
            )
            return result.scalar_one_or_none()

    # sync helpers
    def store_sync(self, *a, **k):
        return self._run(self.store(*a, **k))

    def get_sync(self, *a, **k):
        return self._run(self.get(*a, **k))
