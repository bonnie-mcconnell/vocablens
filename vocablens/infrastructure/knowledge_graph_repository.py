import asyncio
from typing import List, Dict
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vocablens.infrastructure.db.models import KnowledgeGraphEdgeORM


class KnowledgeGraphRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def add_edge(self, source_node: str, target_node: str, relation_type: str, weight: float = 1.0):
        async with self._session_factory() as session:
            await session.execute(
                insert(KnowledgeGraphEdgeORM).values(
                    source_node=source_node,
                    target_node=target_node,
                    relation_type=relation_type,
                    weight=weight,
                )
            )
            await session.commit()

    async def list_edges(self) -> List[Dict]:
        async with self._session_factory() as session:
            result = await session.execute(select(KnowledgeGraphEdgeORM))
            return [dict(row._mapping) for row in result.all()]

    # sync helpers
    def add_edge_sync(self, *a, **k):
        return self._run(self.add_edge(*a, **k))

    def list_edges_sync(self):
        return self._run(self.list_edges())
