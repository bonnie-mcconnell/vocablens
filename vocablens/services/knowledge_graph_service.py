from collections import defaultdict
from typing import Dict, List

from vocablens.infrastructure.repositories import SQLiteVocabularyRepository


class KnowledgeGraphService:
    """
    Builds a dynamic language knowledge graph.
    """

    def __init__(self, repo: SQLiteVocabularyRepository):
        self.repo = repo

    def build_graph(self, user_id: int) -> Dict:

        items = self.repo.list_all(user_id, limit=10000, offset=0)

        graph = {
            "topics": defaultdict(list),
            "difficulty": defaultdict(list),
            "grammar_patterns": defaultdict(list),
        }

        for item in items:

            topic = item.semantic_cluster or "general"
            graph["topics"][topic].append(item.source_text)

            difficulty = getattr(item, "difficulty", "unknown")
            graph["difficulty"][difficulty].append(item.source_text)

            grammar = getattr(item, "grammar_pattern", None)

            if grammar:
                graph["grammar_patterns"][grammar].append(item.source_text)

        return graph

    def topic_scenarios(self, topic: str) -> List[str]:

        scenarios = {
            "food": ["restaurant", "ordering coffee", "grocery shopping"],
            "travel": ["airport", "hotel check-in", "asking directions"],
            "shopping": ["buying clothes", "returning items"],
            "emotion": ["talking about feelings", "sharing experiences"],
        }

        return scenarios.get(topic, ["general conversation"])

    def topic_lessons(self, topic: str) -> List[str]:

        lessons = {
            "food": ["ordering phrases", "menu vocabulary"],
            "travel": ["transport vocabulary", "directions"],
            "shopping": ["numbers", "prices", "transactions"],
        }

        return lessons.get(topic, ["general vocabulary"])