from tests.conftest import run_async
from vocablens.infrastructure.notifications.base import NotificationMessage
from vocablens.infrastructure.notifications.persistent_notifier import PersistentNotificationSink


class FakeInnerSink:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.sent = []

    async def send(self, message):
        self.sent.append(message)
        if self.should_fail:
            raise RuntimeError("delivery failed")


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


class FakeUOW:
    def __init__(self):
        self.notification_deliveries = FakeNotificationDeliveryRepo()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def test_persistent_notification_sink_records_success_status():
    uow = FakeUOW()
    sink = PersistentNotificationSink(FakeInnerSink(), lambda: uow)

    run_async(
        sink.send(
            NotificationMessage(
                user_id=9,
                category="retention:review_reminder",
                title="Review session ready",
                body="You have words ready to review.",
                metadata={"target": "hola"},
            )
        )
    )

    assert uow.notification_deliveries.created[0]["user_id"] == 9
    assert uow.notification_deliveries.status_updates[-1]["status"] == "sent"


def test_persistent_notification_sink_records_failure_status():
    uow = FakeUOW()
    sink = PersistentNotificationSink(FakeInnerSink(should_fail=True), lambda: uow)

    try:
        run_async(
            sink.send(
                NotificationMessage(
                    user_id=2,
                    category="retention:quick_session",
                    title="Quick session suggestion",
                    body="Come back for a short lesson.",
                )
            )
        )
    except RuntimeError:
        pass

    assert uow.notification_deliveries.status_updates[-1]["status"] == "failed"
    assert "delivery failed" in uow.notification_deliveries.status_updates[-1]["error_message"]
