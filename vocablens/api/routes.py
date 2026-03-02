from fastapi import APIRouter, UploadFile, File, HTTPException
from vocablens.services.vocabulary_service import VocabularyService
from vocablens.api.schemas import VocabularyResponse


def create_routes(service: VocabularyService) -> APIRouter:
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

    return router