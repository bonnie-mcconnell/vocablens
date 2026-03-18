from vocablens.services.retention_engine import RetentionEngine
from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.spaced_repetition_service import SpacedRepetitionService


class RetentionProcessor:
    """
    Adjusts retention scheduling based on review events.
    """

    SUPPORTED = {"conversation_turn", "word_learned", "word_reviewed"}

    def __init__(
        self,
        retention: RetentionEngine,
        uow_factory: type[UnitOfWork],
    ):
        self._retention = retention
        self._uow_factory = uow_factory
        self._srs = SpacedRepetitionService()

    def supports(self, event_type: str) -> bool:
        return event_type in self.SUPPORTED

    async def handle(self, event_type: str, user_id: int, payload: dict) -> None:
        await self._retention.record_activity(user_id)

        if event_type != "word_reviewed":
            return

        item_id = payload.get("item_id")
        if item_id is None:
            return

        quality = payload.get("quality")
        if quality is None:
            return

        async with self._uow_factory() as uow:
            item = await uow.vocab.get(user_id, item_id)
            if not item:
                return
            updated = self._srs.review(item, int(quality))
            await uow.vocab.update(updated)
            await uow.commit()
