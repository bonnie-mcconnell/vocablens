import asyncio
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from vocablens.infrastructure.db.models import TranslationCacheORM
from vocablens.infrastructure.db.session import AsyncSession


class PostgresTranslationCacheRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def get(self, text: str, source_lang: str, target_lang: str):
        result = await self.session.execute(
            select(TranslationCacheORM.translation).where(
                TranslationCacheORM.text == text,
                TranslationCacheORM.source_lang == source_lang,
                TranslationCacheORM.target_lang == target_lang,
            )
        )
        return result.scalar_one_or_none()

    async def save(self, text: str, source_lang: str, target_lang: str, translation: str):
        await self.session.execute(
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
        await self.session.commit()

    # sync wrappers
    def get_sync(self, *a, **k): return self._run(self.get(*a, **k))
    def save_sync(self, *a, **k): return self._run(self.save(*a, **k))
