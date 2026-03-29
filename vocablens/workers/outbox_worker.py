from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Awaitable

from vocablens.infrastructure.unit_of_work import UnitOfWork


class OutboxWorker:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        publisher: Callable[[str, dict, str], Awaitable[None]],
        batch_size: int = 100,
    ):
        self._uow_factory = uow_factory
        self._publisher = publisher
        self._batch_size = batch_size

    async def run_once(self) -> int:
        async with self._uow_factory() as uow:
            batch = await uow.outbox_events.claim_unpublished(limit=self._batch_size)
            await uow.commit()

        if not batch:
            return 0

        published_ids: list[int] = []
        failed_ids: list[int] = []
        for event in batch:
            try:
                await self._publisher(event["event_type"], event["payload"], event["dedupe_key"])
                published_ids.append(int(event["id"]))
            except Exception:
                failed_ids.append(int(event["id"]))

        async with self._uow_factory() as uow:
            await uow.outbox_events.mark_published_many(ids=published_ids)
            await uow.outbox_events.increment_retry_many(ids=failed_ids)
            await uow.commit()
        return len(batch)

    async def run_forever(self, idle_sleep_seconds: float = 0.05) -> None:
        while True:
            handled = await self.run_once()
            if handled == 0:
                await asyncio.sleep(idle_sleep_seconds)
