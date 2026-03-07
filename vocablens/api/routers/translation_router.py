from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Query

from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.ocr_service import OCRService
from vocablens.api.schemas import VocabularyResponse, TranslationRequest
from vocablens.api.dependencies import get_current_user
from vocablens.domain.user import User
from vocablens.core.constants import MAX_IMAGE_SIZE, MAX_TEXT_LENGTH


def create_translation_router(
    service: VocabularyService,
    ocr_service: OCRService,
) -> APIRouter:

    router = APIRouter(prefix="/translate", tags=["Translation"])

    @router.post("/", response_model=VocabularyResponse)
    def translate_text(
        payload: TranslationRequest,
        user: User = Depends(get_current_user),
    ):

        item = service.process_text(
            user.id,
            payload.text,
            payload.source_lang,
            payload.target_lang,
        )

        return VocabularyResponse.from_domain(item)

    @router.post("/image", response_model=VocabularyResponse)
    async def translate_image(
        file: UploadFile = File(...),
        source_lang: str = Query("auto"),
        target_lang: str = Query("en"),
        user: User = Depends(get_current_user),
    ):

        image_bytes = await file.read()

        if len(image_bytes) > MAX_IMAGE_SIZE:
            raise HTTPException(400, "File too large")

        text = ocr_service.extract(image_bytes)

        if not text.strip():
            raise HTTPException(400, "No text detected")

        if len(text) > MAX_TEXT_LENGTH:
            raise HTTPException(400, "Text too long")

        item = service.process_text(
            user.id,
            text,
            source_lang,
            target_lang,
        )

        return VocabularyResponse.from_domain(item)

    return router