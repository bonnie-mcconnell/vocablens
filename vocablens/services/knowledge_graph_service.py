import asyncio
from collections import defaultdict
from typing import Dict, List

from vocablens.infrastructure.postgres_vocabulary_repository import PostgresVocabularyRepository
from vocablens.infrastructure.cache.redis_cache import get_cache_backend
from vocablens.config.settings import settings
from vocablens.infrastructure.knowledge_graph_repository import KnowledgeGraphRepository


class KnowledgeGraphService:
    """
    Builds a dynamic language knowledge graph.
    """

    def __init__(self, repo: PostgresVocabularyRepository, kg_repo: KnowledgeGraphRepository):
        self.repo = repo
        self.kg_repo = kg_repo
        self.cache = get_cache_backend() if settings.ENABLE_REDIS_CACHE else None

    def build_graph(self, user_id: int) -> Dict:

        cache_key = f"kg:{user_id}"
        if self.cache:
            cached = asyncio.run(self.cache.get(cache_key))
            if cached:
                return cached

        items = self.repo.list_all_sync(user_id, limit=10000, offset=0)

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

            # persist simple relations
            self.kg_repo.add_edge_sync(item.source_text, topic, "word->topic", 1.0)
            self.kg_repo.add_edge_sync(item.source_text, grammar or "general", "word->grammar", 0.8)

        if self.cache:
            asyncio.run(self.cache.set(cache_key, graph, ttl=600))

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
