from __future__ import annotations

from datetime import datetime, timedelta

from vocablens.core.time import utc_now
from vocablens.infrastructure.unit_of_work import UnitOfWork


ATTRIBUTION_VERSION = "v1"
ATTRIBUTION_WINDOW_DAYS = 30
CONVERSION_EVENT_TYPES = {"upgrade_completed", "subscription_upgraded"}
SUPPORTED_EVENT_TYPES = {
    "session_started",
    "message_sent",
    "lesson_completed",
    "review_completed",
    "upgrade_clicked",
    *CONVERSION_EVENT_TYPES,
}


class ExperimentAttributionService:
    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    async def ensure_exposure(
        self,
        *,
        user_id: int,
        experiment_key: str,
        variant: str,
        exposed_at: datetime,
        assignment_reason: str,
    ):
        async with self._uow_factory() as uow:
            row, created = await uow.experiment_outcome_attributions.create_once(
                user_id=user_id,
                experiment_key=experiment_key,
                variant=variant,
                assignment_reason=assignment_reason,
                attribution_version=ATTRIBUTION_VERSION,
                exposed_at=exposed_at,
                window_end_at=exposed_at + timedelta(days=ATTRIBUTION_WINDOW_DAYS),
            )
            await uow.commit()
        return row, created

    async def record_event(
        self,
        *,
        user_id: int,
        event_type: str,
        occurred_at: datetime | None = None,
    ) -> None:
        if event_type not in SUPPORTED_EVENT_TYPES:
            return
        event_at = occurred_at or utc_now()
        async with self._uow_factory() as uow:
            rows = await uow.experiment_outcome_attributions.list_active_by_user(user_id, event_at)
            for row in rows:
                updates = self._updates_for_event(row=row, event_type=event_type, event_at=event_at)
                if updates:
                    await uow.experiment_outcome_attributions.update(
                        user_id,
                        row.experiment_key,
                        **updates,
                    )
            await uow.commit()

    def _updates_for_event(self, *, row, event_type: str, event_at: datetime) -> dict[str, object]:
        updates: dict[str, object] = {"last_event_at": event_at}
        if event_type == "session_started":
            updates["session_count"] = int(getattr(row, "session_count", 0) or 0) + 1
            if not bool(getattr(row, "retained_d1", False)) and event_at >= row.exposed_at + timedelta(days=1):
                updates["retained_d1"] = True
            if not bool(getattr(row, "retained_d7", False)) and event_at >= row.exposed_at + timedelta(days=7):
                updates["retained_d7"] = True
            return updates
        if event_type == "message_sent":
            updates["message_count"] = int(getattr(row, "message_count", 0) or 0) + 1
            return updates
        if event_type in {"lesson_completed", "review_completed"}:
            updates["learning_action_count"] = int(getattr(row, "learning_action_count", 0) or 0) + 1
            return updates
        if event_type == "upgrade_clicked":
            updates["upgrade_click_count"] = int(getattr(row, "upgrade_click_count", 0) or 0) + 1
            return updates
        if event_type in CONVERSION_EVENT_TYPES:
            if bool(getattr(row, "converted", False)):
                return {}
            updates["converted"] = True
            updates["first_conversion_at"] = event_at
            return updates
        return {}
