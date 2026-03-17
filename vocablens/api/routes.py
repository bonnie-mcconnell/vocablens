from fastapi import APIRouter

from vocablens.api.routers.auth_router import create_auth_router
from vocablens.api.routers.translation_router import create_translation_router
from vocablens.api.routers.vocabulary_router import create_vocabulary_router
from vocablens.api.routers.conversation_router import create_conversation_router
from vocablens.api.routers.lesson_router import create_lesson_router
from vocablens.api.routers.scenario_router import create_scenario_router
from vocablens.api.routers.learning_router import create_learning_router

from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.ocr_service import OCRService
from vocablens.services.conversation_service import ConversationService
from vocablens.services.lesson_generation_service import LessonGenerationService
from vocablens.services.scenario_service import ScenarioService
from vocablens.services.speech_conversation_service import SpeechConversationService
from vocablens.services.learning_roadmap_service import LearningRoadmapService
from vocablens.services.knowledge_graph_service import KnowledgeGraphService

from vocablens.infrastructure.postgres_user_repository import PostgresUserRepository


def create_routes(
    vocab_service: VocabularyService,
    ocr_service: OCRService,
    user_repo: PostgresUserRepository,
    conversation_service: ConversationService,
    speech_service: SpeechConversationService,
    lesson_service: LessonGenerationService,
    scenario_service: ScenarioService,
    roadmap_service: LearningRoadmapService,
    graph_service: KnowledgeGraphService,
) -> APIRouter:

    router = APIRouter()

    router.include_router(create_auth_router(user_repo=user_repo))

    router.include_router(
        create_translation_router(
            service=vocab_service,
            ocr_service=ocr_service,
        )
    )

    router.include_router(
        create_vocabulary_router(vocab_service)
    )

    router.include_router(
        create_conversation_router(
            conversation_service,
            speech_service,
        )
    )

    router.include_router(
        create_lesson_router(lesson_service)
    )

    router.include_router(
        create_scenario_router(scenario_service)
    )

    router.include_router(
        create_learning_router(
            roadmap_service,
            graph_service,
        )
    )

    return router
