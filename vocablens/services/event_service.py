from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Any

from vocablens.infrastructure.unit_of_work import UnitOfWork
from vocablens.services.experiment_attribution_service import ExperimentAttributionService


SUPPORTED_EVENT_TYPES = {
    "lesson_completed",
    "lesson_recommended",
    "message_sent",
    "mistake_made",
    "knowledge_updated",
    "review_completed",
    "session_started",
    "session_ended",
    "subscription_upgraded",
    "paywall_viewed",
    "upgrade_clicked",
    "upgrade_completed",
    "referral_invite_created",
    "referral_redeemed",
    "referral_reward_granted",
    "progress_shared",
    "xp_awarded",
    "badge_unlocked",
    "streak_milestone_reached",
    "daily_mission_generated",
    "daily_mission_completed",
    "skip_shield_used",
    "reward_chest_unlocked",
}


_LOGGER = logging.getLogger(__name__)


class EventService:
    def __init__(
        self,
        uow_factory: type[UnitOfWork],
        experiment_attribution_service: ExperimentAttributionService | None = None,
        *,
        use_buffer: bool = True,
        buffer_size: int = 1000,
        ingest_mode: str = "best_effort",
    ):
        if ingest_mode not in {"best_effort", "durable"}:
            raise ValueError("ingest_mode must be either 'best_effort' or 'durable'")
        self._uow_factory = uow_factory
        self._attribution = experiment_attribution_service
        self._ingest_mode = ingest_mode
        self._use_buffer = use_buffer and ingest_mode == "best_effort"
        self._queue: asyncio.Queue[dict[str, Any]] | None = (
            asyncio.Queue(maxsize=buffer_size) if self._use_buffer else None
        )
        self._drain_task: asyncio.Task | None = None
        self._pending_tasks: set[asyncio.Task] = set()

    async def track_event(self, user_id: int, event_type: str, payload: dict | None = None) -> None:
        self._validate_event_type(event_type)
        envelope = {
            "user_id": user_id,
            "event_type": event_type,
            "payload": dict(payload or {}),
        }
        if self._ingest_mode == "durable":
            await self._persist(envelope)
            return

        if self._queue is not None:
            self._ensure_drain_task()
            try:
                self._queue.put_nowait(envelope)
                return
            except asyncio.QueueFull:
                pass
        self._spawn_persist_task(envelope)

    async def get_user_events(self, user_id: int, limit: int = 1000):
        await self.flush()
        async with self._uow_factory() as uow:
            events = await uow.events.list_by_user(user_id, limit=limit)
            await uow.commit()
        return events

    async def get_events_by_type(self, event_type: str, limit: int = 1000):
        await self.flush()
        async with self._uow_factory() as uow:
            events = await uow.events.list_by_type(event_type, limit=limit)
            await uow.commit()
        return events

    async def flush(self) -> None:
        if self._queue is not None:
            self._ensure_drain_task()
            await self._queue.join()
        if self._pending_tasks:
            await asyncio.gather(*tuple(self._pending_tasks), return_exceptions=True)

    async def close(self) -> None:
        await self.flush()
        if self._drain_task is not None:
            self._drain_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._drain_task
            self._drain_task = None

    def _spawn_persist_task(self, envelope: dict[str, Any]) -> None:
        task = asyncio.create_task(self._persist_best_effort(envelope))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def _ensure_drain_task(self) -> None:
        if self._queue is None:
            return
        if self._drain_task and not self._drain_task.done():
            return
        self._drain_task = asyncio.create_task(self._drain_loop())

    async def _drain_loop(self) -> None:
        assert self._queue is not None
        while True:
            envelope = await self._queue.get()
            try:
                await self._persist_best_effort(envelope)
            finally:
                self._queue.task_done()

    async def _persist_best_effort(self, envelope: dict[str, Any]) -> None:
        try:
            await self._persist(envelope)
        except Exception:
            _LOGGER.exception(
                "Best-effort event ingestion dropped event",
                extra={
                    "event_type": envelope.get("event_type"),
                    "user_id": envelope.get("user_id"),
                },
            )

    async def _persist(self, envelope: dict[str, Any]) -> None:
        async with self._uow_factory() as uow:
            await uow.events.record(
                user_id=envelope["user_id"],
                event_type=envelope["event_type"],
                payload=envelope["payload"],
            )
            await self._project_state(uow, envelope)
            await uow.commit()
        if self._attribution is not None:
            await self._attribution.record_event(
                user_id=envelope["user_id"],
                event_type=envelope["event_type"],
            )

    def _validate_event_type(self, event_type: str) -> None:
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise ValueError(f"Unsupported event type '{event_type}'")

    async def _project_state(self, uow, envelope: dict[str, Any]) -> None:
        event_type = envelope["event_type"]
        if event_type not in {"message_sent", "review_completed", "lesson_completed", "progress_shared"}:
            return
        engagement = await uow.engagement_states.get_or_create(envelope["user_id"])
        stats = dict(getattr(engagement, "interaction_stats", {}) or {})
        key_map = {
            "message_sent": "messages_sent",
            "review_completed": "reviews_completed",
            "lesson_completed": "lessons_completed",
            "progress_shared": "progress_shares",
        }
        key = key_map[event_type]
        stats[key] = int(stats.get(key, 0) or 0) + 1
        await uow.engagement_states.update(
            envelope["user_id"],
            interaction_stats=stats,
        )
