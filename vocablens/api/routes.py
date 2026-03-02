from fastapi import APIRouter, UploadFile, File, HTTPException
from vocablens.services.vocabulary_service import VocabularyService
from vocablens.api.schemas import VocabularyResponse
from vocablens.services.ocr_service import OCRService

def create_routes(
    service: VocabularyService,
    ocr_service: OCRService,
) -> APIRouter:
    router = APIRouter()

    @router.post("/translate", response_model=VocabularyResponse)
    async def translate_text(
        text: str,
        source_lang: str,
        target_lang: str,
    ):
        try:
            item = service.process_text(text, source_lang, target_lang)
            return VocabularyResponse.from_domain(item)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        

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
    
    return router