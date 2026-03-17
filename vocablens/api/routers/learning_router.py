from fastapi import APIRouter, Depends

from vocablens.api.dependencies import (
    get_current_user,
    get_knowledge_graph_service,
    get_learning_roadmap_service,
)
from vocablens.domain.user import User
from vocablens.services.knowledge_graph_service import KnowledgeGraphService
from vocablens.services.learning_roadmap_service import LearningRoadmapService


def create_learning_router() -> APIRouter:

    router = APIRouter(
        prefix="/learning",
        tags=["Learning"],
    )

    @router.get("/roadmap")
    async def roadmap(
        user: User = Depends(get_current_user),
        roadmap_service: LearningRoadmapService = Depends(get_learning_roadmap_service),
    ):

        return await roadmap_service.generate_today_plan(user.id)

    @router.get("/graph")
    def graph(
        user: User = Depends(get_current_user),
        graph_service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
    ):

        return graph_service.build_graph(user.id)

    return router
