from collections import defaultdict
from typing import Dict, List, Optional

from vocablens.infrastructure.postgres_vocabulary_repository import PostgresVocabularyRepository


class LearningGraphService:
    """
    Builds a vocabulary graph grouped by semantic cluster.
    """

    def __init__(self, repo: PostgresVocabularyRepository):
        self.repo = repo

    def build_graph(self, user_id: int) -> Dict[str, List[str]]:

        items = self.repo.list_all_sync(user_id, limit=10000, offset=0)

        graph = defaultdict(list)

        for item in items:

            cluster = item.semantic_cluster or "general"

            graph[cluster].append(item.source_text)

        return graph

    def recommend_next_cluster(self, user_id: int) -> Optional[str]:

        graph = self.build_graph(user_id)

        smallest_cluster = None
        smallest_size = 999999

        for cluster, words in graph.items():

            if len(words) < smallest_size:
                smallest_cluster = cluster
                smallest_size = len(words)

        return smallest_cluster
