from fastapi import APIRouter, Depends

from vocablens.api.dependencies_interaction_api import (
    get_current_user,
    get_knowledge_graph_service,
    get_learning_roadmap_service,
)
from vocablens.api.schemas import APIResponse
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
        data = await roadmap_service.generate_today_plan(user.id)
        return APIResponse(
            data=data,
            meta={
                "source": "learning.roadmap",
                "difficulty": (data.get("next_action") or {}).get("lesson_difficulty"),
                "next_action": (data.get("next_action") or {}).get("action"),
            },
        )

    @router.get("/graph", response_model=APIResponse)
    async def graph(
        user: User = Depends(get_current_user),
        graph_service: KnowledgeGraphService = Depends(get_knowledge_graph_service),
    ):
        return APIResponse(
            data=await graph_service.build_graph(user.id),
            meta={"source": "learning.graph"},
        )

    return router
