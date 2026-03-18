from vocablens.infrastructure.notifications.base import NotificationMessage, NotificationSink
from vocablens.services.retention_engine import RetentionEngine


class RetentionNotificationProcessor:
    """
    Emits retention nudges through the notification abstraction.
    """

    SUPPORTED = {"conversation_turn", "word_learned", "word_reviewed"}

    def __init__(self, retention: RetentionEngine, notifier: NotificationSink):
        self._retention = retention
        self._notifier = notifier

    def supports(self, event_type: str) -> bool:
        return event_type in self.SUPPORTED

    async def handle(self, event_type: str, user_id: int, payload: dict) -> None:
        assessment = await self._retention.assess_user(user_id)
        if assessment.state == "active" and not assessment.is_high_engagement:
            return

        for action in assessment.suggested_actions[:2]:
            await self._notifier.send(
                NotificationMessage(
                    user_id=user_id,
                    category=f"retention:{action.kind}",
                    title=self._title_for(action.kind, assessment.state),
                    body=action.reason,
                    metadata={
                        "state": assessment.state,
                        "target": action.target,
                        "drop_off_risk": assessment.drop_off_risk,
                    },
                )
            )

    def _title_for(self, action_kind: str, state: str) -> str:
        if action_kind == "review_reminder":
            return "Review session ready"
        if action_kind == "quick_session":
            return "Quick session suggestion"
        if action_kind == "resurface_weak_vocabulary":
            return "Weak vocabulary to revisit"
        if action_kind == "streak_nudge":
            return "Keep your streak alive"
        return f"Retention update ({state})"
