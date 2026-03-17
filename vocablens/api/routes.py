from fastapi import APIRouter

from vocablens.api.routers.auth_router import create_auth_router
from vocablens.api.routers.conversation_router import create_conversation_router
from vocablens.api.routers.learning_router import create_learning_router
from vocablens.api.routers.lesson_router import create_lesson_router
from vocablens.api.routers.scenario_router import create_scenario_router
from vocablens.api.routers.translation_router import create_translation_router
from vocablens.api.routers.vocabulary_router import create_vocabulary_router


def create_routes() -> APIRouter:

    router = APIRouter()

    router.include_router(create_auth_router())
    router.include_router(create_translation_router())
    router.include_router(create_vocabulary_router())
    router.include_router(create_conversation_router())
    router.include_router(create_lesson_router())
    router.include_router(create_scenario_router())
    router.include_router(create_learning_router())

    return router
