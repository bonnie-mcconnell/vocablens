from types import SimpleNamespace

from tests.conftest import run_async
from vocablens.services.notification_state_service import NotificationStateService


class FakeNotificationStatesRepo:
    def __init__(self):
        self.row = None

    async def get_or_create(self, user_id: int):
        if self.row is None or self.row.user_id != user_id:
            self.row = SimpleNamespace(
                user_id=user_id,
                preferred_channel="push",
                preferred_time_of_day=18,
                frequency_limit=2,
                lifecycle_stage=None,
                lifecycle_policy={},
                lifecycle_policy_version="v1",
                suppression_reason=None,
                suppressed_until=None,
                cooldown_until=None,
                sent_count_day=None,
                sent_count_today=0,
                last_sent_at=None,
                last_delivery_channel=None,
                last_delivery_status=None,
                last_delivery_category=None,
                last_reference_id=None,
                last_decision_at=None,
                last_decision_reason=None,
                updated_at=None,
            )
        return self.row

    async def update(self, user_id: int, **kwargs):
        row = await self.get_or_create(user_id)
        for key, value in kwargs.items():
            if value is not None:
                setattr(row, key, value)
        return row


class FakeNotificationSuppressionEventsRepo:
    def __init__(self):
        self.created = []

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(**kwargs)


class FakeNotificationPolicyRegistryRepo:
    async def get(self, policy_key: str):
        return SimpleNamespace(
            policy_key=policy_key,
            status="active",
            is_killed=False,
            policy={
                "cooldown_hours": 4,
                "default_frequency_limit": 2,
                "default_preferred_time_of_day": 18,
                "stage_policies": {
                    "new_user": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                    "activating": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                    "engaged": {"lifecycle_notifications_enabled": False, "suppression_reason": "engaged stage suppresses proactive lifecycle messaging", "recovery_window_hours": 24},
                    "at_risk": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                    "churned": {"lifecycle_notifications_enabled": True, "suppression_reason": None, "recovery_window_hours": 0},
                },
                "suppression_overrides": [
                    {
                        "source_context": "lifecycle_service.notification",
                        "stage": "engaged",
                        "lifecycle_notifications_enabled": False,
                        "suppression_reason": "engaged stage suppresses proactive lifecycle messaging",
                        "recovery_window_hours": 24,
                    }
                ],
            },
        )


class FakeUOW:
    def __init__(self):
        self.notification_states = FakeNotificationStatesRepo()
        self.notification_suppression_events = FakeNotificationSuppressionEventsRepo()
        self.notification_policy_registries = FakeNotificationPolicyRegistryRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_notification_state_service_applies_engaged_lifecycle_suppression():
    uow = FakeUOW()
    service = NotificationStateService(lambda: uow)

    state = run_async(
        service.apply_lifecycle_policy(
            user_id=3,
            lifecycle_stage="engaged",
            source="lifecycle_service.evaluate",
            reference_id="lifecycle:3",
        )
    )

    assert state.lifecycle_policy["lifecycle_notifications_enabled"] is False
    assert state.suppression_reason == "engaged stage suppresses proactive lifecycle messaging"
    assert uow.notification_suppression_events.created[0]["event_type"] == "lifecycle_policy_updated"


def test_notification_state_service_records_sent_delivery_cadence():
    uow = FakeUOW()
    service = NotificationStateService(lambda: uow)

    state = run_async(
        service.record_delivery(
            user_id=5,
            category="retention:review_reminder",
            channel="email",
            status="sent",
            reference_id="lifecycle:5",
        )
    )

    assert state.sent_count_today == 1
    assert state.last_delivery_channel == "email"
    assert state.last_delivery_status == "sent"
    assert state.cooldown_until is not None
