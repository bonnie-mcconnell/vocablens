from collections import defaultdict
from typing import Dict, List, Optional

from vocablens.infrastructure.unit_of_work import UnitOfWork


class LearningGraphService:
    """
    Builds a vocabulary graph grouped by semantic cluster.
    """

    def __init__(self, uow_factory: type[UnitOfWork]):
        self._uow_factory = uow_factory

    def build_graph(self, user_id: int) -> Dict[str, List[str]]:

        # this service is used in sync contexts; run blocking I/O via helper
        import anyio

        async def _load():
            async with self._uow_factory() as uow:
                return await uow.vocab.list_all(user_id, limit=10000, offset=0)

        items = anyio.run(_load)

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
