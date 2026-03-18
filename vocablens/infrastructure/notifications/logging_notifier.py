from vocablens.infrastructure.logging.logger import get_logger
from vocablens.infrastructure.notifications.base import NotificationMessage


logger = get_logger("notifications")


class LoggingNotificationSink:
    """
    Placeholder notifier for future delivery channels.
    """

    async def send(self, message: NotificationMessage) -> None:
        logger.info(
            "notification_emitted",
            extra={
                "user_id": message.user_id,
                "category": message.category,
                "title": message.title,
                "body": message.body,
                "metadata": message.metadata or {},
            },
        )
