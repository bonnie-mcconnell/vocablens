import asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vocablens.infrastructure.db.models import TranslationCacheORM


class PostgresTranslationCacheRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def get(self, text: str, source_lang: str, target_lang: str):
        async with self._session_factory() as session:
            result = await session.execute(
                select(TranslationCacheORM.translation).where(
                    TranslationCacheORM.text == text,
                    TranslationCacheORM.source_lang == source_lang,
                    TranslationCacheORM.target_lang == target_lang,
                )
            )
            return result.scalar_one_or_none()

    async def save(self, text: str, source_lang: str, target_lang: str, translation: str):
        async with self._session_factory() as session:
            await session.execute(
                insert(TranslationCacheORM)
                .values(
                    text=text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    translation=translation,
                )
                .on_conflict_do_update(
                    index_elements=["text", "source_lang", "target_lang"],
                    set_={"translation": translation},
                )
            )
            await session.commit()

    # sync wrappers
    def get_sync(self, *a, **k): return self._run(self.get(*a, **k))
    def save_sync(self, *a, **k): return self._run(self.save(*a, **k))
