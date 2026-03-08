from fastapi import APIRouter

from vocablens.api.routers.auth_router import create_auth_router
from vocablens.api.routers.translation_router import create_translation_router
from vocablens.api.routers.vocabulary_router import create_vocabulary_router

from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.ocr_service import OCRService
from vocablens.infrastructure.repositories_users import SQLiteUserRepository


def create_routes(
    service: VocabularyService,
    ocr_service: OCRService,
    user_repo: SQLiteUserRepository,
) -> APIRouter:

    router = APIRouter()

    # Authentication
    router.include_router(create_auth_router(user_repo))

    # OCR + Translation pipeline
    router.include_router(
        create_translation_router(
            service=service,
            ocr_service=ocr_service,
        )
    )

    # Vocabulary management
    router.include_router(
        create_vocabulary_router(
            service=service,
            user_repo=user_repo,
        )
    )

    return router