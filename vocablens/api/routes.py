from fastapi import APIRouter, UploadFile, File, HTTPException
import logging

from vocablens.services.vocabulary_service import VocabularyService
from vocablens.api.schemas import VocabularyResponse, TranslationRequest
from vocablens.services.ocr_service import OCRService
from vocablens.domain.errors import NotFoundError

logger = logging.getLogger(__name__)


def create_routes(
    service: VocabularyService,
    ocr_service: OCRService,
) -> APIRouter:

    router = APIRouter()

    @router.post("/translate", response_model=VocabularyResponse)
    def translate_text(payload: TranslationRequest):
        item = service.process_text(
            payload.text,
            payload.source_lang,
            payload.target_lang,
        )
        return VocabularyResponse.from_domain(item)
    
    @router.post("/translate/image", response_model=VocabularyResponse)
    async def translate_image(
        file: UploadFile = File(...),
        source_lang: str = "auto",
        target_lang: str = "en",
    ):
        image_bytes = await file.read()
        extracted = ocr_service.extract(image_bytes)
        item = service.process_text(extracted, source_lang, target_lang)
        return VocabularyResponse.from_domain(item)


    @router.get("/vocabulary", response_model=list[VocabularyResponse])
    def list_vocabulary(limit: int = 50, offset: int = 0):
        items = service.list_vocabulary(limit=limit, offset=offset)
        return [VocabularyResponse.from_domain(i) for i in items]

    @router.post("/vocabulary/{item_id}/review", response_model=VocabularyResponse)
    def review_item(item_id: int):
        try:
            updated = service.review_item(item_id)
            logger.info("review_incremented item_id=%s", item_id)
            return VocabularyResponse.from_domain(updated)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/vocabulary/due", response_model=list[VocabularyResponse])
    def due_items():
        items = service.list_due_items()
        return [VocabularyResponse.from_domain(i) for i in items]
    
    return router