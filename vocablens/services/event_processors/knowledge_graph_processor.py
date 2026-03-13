from typing import List

from vocablens.services.knowledge_graph_service import KnowledgeGraphService


class KnowledgeGraphProcessor:
    """
    Enriches knowledge graph observations when new words or conversations occur.
    Currently keeps in-memory observations; persistence can be added later.
    """

    SUPPORTED = {"word_learned", "conversation_turn"}

    def __init__(self, graph_service: KnowledgeGraphService):
        self._graph = graph_service
        self._observations = {}

    def supports(self, event_type: str) -> bool:
        return event_type in self.SUPPORTED

    def handle(self, event_type: str, user_id: int, payload: dict) -> None:

        if event_type == "word_learned":
            words = payload.get("words", [])
            self._add_observation(user_id, words)

        elif event_type == "conversation_turn":
            new_words = payload.get("new_words", [])
            self._add_observation(user_id, new_words)

    def _add_observation(self, user_id: int, words: List[str]) -> None:
        if not words:
            return
        bucket = self._observations.setdefault(user_id, [])
        bucket.extend(words)
        # Placeholder: future integration can persist clusters or annotations.
