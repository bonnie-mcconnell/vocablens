import json
from typing import Dict, List, Protocol, Any

from vocablens.services.learning_events import LearningEvent, ConversationTurnEvent
from vocablens.infrastructure.postgres_learning_event_repository import PostgresLearningEventRepository


class LearningEventProcessor(Protocol):
    """
    Interface for learning event processors.
    """

    def supports(self, event_type: str) -> bool:
        ...

    def handle(self, event_type: str, user_id: int, payload: Dict[str, Any]) -> None:
        ...


class LearningEventService:
    """
    Central learning event bus.
    Records events to the database and dispatches them to processors.
    """

    def __init__(
        self,
        processors: List[LearningEventProcessor],
        repo: PostgresLearningEventRepository,
    ):
        self._processors = processors
        self._repo = repo

    async def record(self, event_type: str, user_id: int, payload: Dict[str, Any]) -> None:

        model = self._validate(event_type, payload)
        await self._persist(event_type, user_id, model.model_dump())
        await self._dispatch(event_type, user_id, model.model_dump())

    def _validate(self, event_type: str, payload: Dict[str, Any]) -> LearningEvent:
        if event_type == "conversation_turn":
            return ConversationTurnEvent(**payload)
        if event_type == "word_learned":
            from vocablens.services.learning_events import WordLearnedEvent
            return WordLearnedEvent(**payload)
        if event_type == "word_reviewed":
            from vocablens.services.learning_events import WordReviewedEvent
            return WordReviewedEvent(**payload)
        if event_type == "mistake_detected":
            from vocablens.services.learning_events import MistakeDetectedEvent
            return MistakeDetectedEvent(**payload)
        if event_type == "skill_update":
            from vocablens.services.learning_events import SkillUpdateEvent
            return SkillUpdateEvent(**payload)
        # fallback to conversation event structure
        return ConversationTurnEvent(**payload)

    # -----------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------

    async def _persist(self, event_type: str, user_id: int, payload: Dict[str, Any]) -> None:

        await self._repo.record(user_id=user_id, event_type=event_type, payload_json=json.dumps(payload))

    async def _dispatch(self, event_type: str, user_id: int, payload: Dict[str, Any]) -> None:

        for processor in self._processors:
            if processor.supports(event_type):
                processor.handle(event_type, user_id, payload)
