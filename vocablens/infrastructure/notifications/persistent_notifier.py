from vocablens.infrastructure.notifications.base import NotificationMessage, NotificationSink


class PersistentNotificationSink:
    """
    Persists notification delivery attempts and status around an inner sink.
    """

    def __init__(self, inner: NotificationSink, uow_factory):
        self._inner = inner
        self._uow_factory = uow_factory

    async def send(self, message: NotificationMessage) -> None:
        async with self._uow_factory() as uow:
            delivery = await uow.notification_deliveries.create_attempt(
                user_id=message.user_id,
                category=message.category,
                provider=self._provider_name(),
                title=message.title,
                body=message.body,
                payload=message.metadata or {},
            )
            await uow.commit()

        try:
            await self._inner.send(message)
        except Exception as exc:
            async with self._uow_factory() as uow:
                await uow.notification_deliveries.mark_status(
                    delivery.id,
                    "failed",
                    error_message=str(exc),
                )
                await uow.commit()
            raise

        async with self._uow_factory() as uow:
            await uow.notification_deliveries.mark_status(delivery.id, "sent")
            await uow.commit()

    def _provider_name(self) -> str:
        return self._inner.__class__.__name__.lower()
