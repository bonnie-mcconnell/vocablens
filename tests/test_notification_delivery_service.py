from tests.conftest import run_async
from vocablens.infrastructure.notifications.base import NotificationMessage
from vocablens.services.notification_delivery_service import NotificationDeliveryService


class FakeBackend:
    def __init__(self, channel: str, failures_before_success: int = 0):
        self.channel = channel
        self.failures_before_success = failures_before_success
        self.calls = []

    async def send(self, message: NotificationMessage) -> None:
        self.calls.append(message)
        if len(self.calls) <= self.failures_before_success:
            raise RuntimeError("temporary delivery failure")


class FakeNotificationDeliveryRepo:
    def __init__(self):
        self.created = []
        self.status_updates = []

    async def create_attempt(self, **kwargs):
        delivery = type("Delivery", (), {"id": len(self.created) + 1})()
        self.created.append(kwargs)
        return delivery

    async def mark_status(self, delivery_id: int, status: str, error_message: str | None = None):
        self.status_updates.append(
            {"delivery_id": delivery_id, "status": status, "error_message": error_message}
        )


class FakeNotificationStatesRepo:
    def __init__(self):
        self.row = type(
            "NotificationState",
            (),
            {
                "user_id": None,
                "sent_count_day": None,
                "sent_count_today": 0,
                "cooldown_until": None,
                "last_sent_at": None,
            },
        )()

    async def get_or_create(self, user_id: int):
        self.row.user_id = user_id
        return self.row

    async def update(self, user_id: int, **kwargs):
        self.row.user_id = user_id
        for key, value in kwargs.items():
            if value is not None:
                setattr(self.row, key, value)
        return self.row


class FakeUOW:
    def __init__(self):
        self.notification_deliveries = FakeNotificationDeliveryRepo()
        self.notification_states = FakeNotificationStatesRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


async def _no_sleep(seconds: float):
    return None


def test_notification_delivery_service_retries_with_backoff_until_success():
    uow = FakeUOW()
    backend = FakeBackend("email", failures_before_success=1)
    service = NotificationDeliveryService(
        lambda: uow,
        {"email": backend},
        max_attempts=3,
        sleeper=_no_sleep,
    )

    result = run_async(
        service.send(
            NotificationMessage(
                user_id=1,
                category="retention:review_reminder",
                title="Review ready",
                body="Come back for a quick review.",
                metadata={"channel": "email"},
            )
        )
    )

    assert result.success is True
    assert result.attempts == 2
    assert len(backend.calls) == 2
    assert len(uow.notification_deliveries.created) == 2
    assert uow.notification_deliveries.status_updates[0]["status"] == "failed"
    assert uow.notification_deliveries.status_updates[-1]["status"] == "sent"
    assert uow.notification_states.row.sent_count_today == 1
    assert uow.notification_states.row.last_delivery_status == "sent"


def test_notification_delivery_service_records_final_failure():
    uow = FakeUOW()
    backend = FakeBackend("push", failures_before_success=5)
    service = NotificationDeliveryService(
        lambda: uow,
        {"push": backend},
        max_attempts=2,
        sleeper=_no_sleep,
    )

    result = run_async(
        service.send(
            NotificationMessage(
                user_id=4,
                category="retention:streak_nudge",
                title="Keep your streak going",
                body="Don’t lose today’s streak.",
                metadata={"channel": "push"},
            )
        )
    )

    assert result.success is False
    assert result.attempts == 2
    assert "temporary delivery failure" in result.error
    assert len(uow.notification_deliveries.created) == 2
    assert uow.notification_deliveries.status_updates[-1]["status"] == "failed"
    assert uow.notification_states.row.last_delivery_status == "failed"


def test_notification_delivery_service_batches_by_channel():
    uow = FakeUOW()
    email = FakeBackend("email")
    in_app = FakeBackend("in_app")
    service = NotificationDeliveryService(
        lambda: uow,
        {"email": email, "in_app": in_app},
        max_attempts=1,
        batch_size=2,
        sleeper=_no_sleep,
    )

    results = run_async(
        service.send_batch(
            [
                NotificationMessage(user_id=1, category="a", title="A", body="A", metadata={"channel": "email"}),
                NotificationMessage(user_id=2, category="b", title="B", body="B", metadata={"channel": "in_app"}),
                NotificationMessage(user_id=3, category="c", title="C", body="C", metadata={"channel": "email"}),
            ]
        )
    )

    assert len(results) == 3
    assert len(email.calls) == 2
    assert len(in_app.calls) == 1
    assert all(result.success for result in results)
