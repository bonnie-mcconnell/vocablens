from fastapi import APIRouter, Depends

from vocablens.api.dependencies_interaction_api import get_current_user, get_lesson_generation_service
from vocablens.api.schemas import APIResponse
from vocablens.domain.user import User
from vocablens.services.lesson_generation_service import LessonGenerationService


def create_lesson_router() -> APIRouter:

    router = APIRouter(
        prefix="/lesson",
        tags=["Lessons"],
    )

    @router.get("/generate", response_model=APIResponse)
    async def generate_lesson(
        user: User = Depends(get_current_user),
        service: LessonGenerationService = Depends(get_lesson_generation_service),
    ):

        lesson = await service.generate_lesson(user.id)
        next_action = lesson.get("next_action") if isinstance(lesson, dict) else {}
        if not isinstance(next_action, dict):
            next_action = {}
        return APIResponse(
            data=lesson,
            meta={
                "source": "lesson.generate",
                "difficulty": next_action.get("lesson_difficulty"),
                "next_action": next_action.get("action"),
                "corrections": [],
            },
        )

    return router
