import json
import sqlite3
from typing import Dict, List, Protocol, Any


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
        db_path: str = "vocablens.db",
    ):
        self._processors = processors
        self._db_path = db_path

    def record(self, event_type: str, user_id: int, payload: Dict[str, Any]) -> None:

        self._persist(event_type, user_id, payload)
        self._dispatch(event_type, user_id, payload)

    # -----------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------

    def _persist(self, event_type: str, user_id: int, payload: Dict[str, Any]) -> None:

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO learning_events (user_id, event_type, payload_json)
                VALUES (?, ?, ?)
                """,
                (user_id, event_type, json.dumps(payload)),
            )

    def _dispatch(self, event_type: str, user_id: int, payload: Dict[str, Any]) -> None:

        for processor in self._processors:
            if processor.supports(event_type):
                processor.handle(event_type, user_id, payload)
