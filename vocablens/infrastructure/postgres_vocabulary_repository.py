import asyncio
from typing import List
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import VocabularyORM
from vocablens.domain.models import VocabularyItem


def _map_row(row: VocabularyORM) -> VocabularyItem:
    return VocabularyItem(
        id=row.id,
        source_text=row.source_text,
        translated_text=row.translated_text,
        source_lang=row.source_lang,
        target_lang=row.target_lang,
        created_at=row.created_at,
        last_reviewed_at=row.last_reviewed_at,
        review_count=row.review_count,
        ease_factor=row.ease_factor,
        interval=row.interval,
        repetitions=row.repetitions,
        next_review_due=row.next_review_due,
        example_source_sentence=row.example_source_sentence,
        example_translated_sentence=row.example_translated_sentence,
        grammar_note=row.grammar_note,
        semantic_cluster=row.semantic_cluster,
    )


class PostgresVocabularyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # sync-friendly wrappers
    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    # Public API (async)
    async def add(self, user_id: int, item: VocabularyItem) -> VocabularyItem:
        obj = VocabularyORM(
            user_id=user_id,
            source_text=item.source_text,
            translated_text=item.translated_text,
            source_lang=item.source_lang,
            target_lang=item.target_lang,
            created_at=item.created_at,
            last_reviewed_at=item.last_reviewed_at,
            review_count=item.review_count,
            ease_factor=item.ease_factor,
            interval=item.interval,
            repetitions=item.repetitions,
            next_review_due=item.next_review_due,
            example_source_sentence=item.example_source_sentence,
            example_translated_sentence=item.example_translated_sentence,
            grammar_note=item.grammar_note,
            semantic_cluster=item.semantic_cluster,
        )
        self.session.add(obj)
        await self.session.commit()
        await self.session.refresh(obj)
        return _map_row(obj)

    async def list_all(self, user_id: int, limit: int, offset: int) -> List[VocabularyItem]:
        result = await self.session.execute(
            select(VocabularyORM)
            .where(VocabularyORM.user_id == user_id)
            .order_by(VocabularyORM.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_map_row(r) for r in result.scalars().all()]

    async def list_due(self, user_id: int) -> List[VocabularyItem]:
        result = await self.session.execute(
            select(VocabularyORM).where(
                VocabularyORM.user_id == user_id,
                VocabularyORM.next_review_due.is_not(None),
                VocabularyORM.next_review_due <= func.now(),
            ).order_by(VocabularyORM.next_review_due.asc())
        )
        return [_map_row(r) for r in result.scalars().all()]

    async def get(self, user_id: int, item_id: int):
        result = await self.session.execute(
            select(VocabularyORM).where(
                VocabularyORM.id == item_id,
                VocabularyORM.user_id == user_id,
            )
        )
        row = result.scalar_one_or_none()
        return _map_row(row) if row else None

    async def exists(self, user_id: int, source_text: str, source_lang: str, target_lang: str) -> bool:
        result = await self.session.execute(
            select(VocabularyORM.id).where(
                VocabularyORM.user_id == user_id,
                VocabularyORM.source_text == source_text,
                VocabularyORM.source_lang == source_lang,
                VocabularyORM.target_lang == target_lang,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def update(self, item: VocabularyItem) -> VocabularyItem:
        await self.session.execute(
            update(VocabularyORM)
            .where(VocabularyORM.id == item.id)
            .values(
                last_reviewed_at=item.last_reviewed_at,
                review_count=item.review_count,
                ease_factor=item.ease_factor,
                interval=item.interval,
                repetitions=item.repetitions,
                next_review_due=item.next_review_due,
            )
        )
        await self.session.commit()
        return item

    async def update_enrichment(
        self,
        item_id: int,
        example_source: str | None,
        example_translation: str | None,
        grammar: str | None,
        cluster: str | None,
    ):
        await self.session.execute(
            update(VocabularyORM)
            .where(VocabularyORM.id == item_id)
            .values(
                example_source_sentence=example_source,
                example_translated_sentence=example_translation,
                grammar_note=grammar,
                semantic_cluster=cluster,
            )
        )
        await self.session.commit()
