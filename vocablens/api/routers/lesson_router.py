from fastapi import APIRouter, Depends

from vocablens.api.dependencies import get_current_user, get_lesson_generation_service
from vocablens.domain.user import User
from vocablens.services.lesson_generation_service import LessonGenerationService


def create_lesson_router() -> APIRouter:

    router = APIRouter(
        prefix="/lesson",
        tags=["Lessons"],
    )

    @router.get("/generate")
    def generate_lesson(
        user: User = Depends(get_current_user),
        service: LessonGenerationService = Depends(get_lesson_generation_service),
    ):

        lesson = service.generate_lesson(user.id)

        return lesson

    return router
