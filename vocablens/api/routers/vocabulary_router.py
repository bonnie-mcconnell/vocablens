from fastapi import APIRouter, Depends, HTTPException, Query

from vocablens.services.vocabulary_service import VocabularyService
from vocablens.api.schemas import VocabularyResponse, ReviewRequest
from vocablens.api.dependencies import get_current_user
from vocablens.domain.errors import NotFoundError
from vocablens.domain.user import User
from vocablens.core.constants import REVIEW_RATINGS


def create_vocabulary_router(service: VocabularyService) -> APIRouter:

    router = APIRouter(prefix="/vocab", tags=["Vocabulary"])

    @router.get("/", response_model=list[VocabularyResponse])
    def list_vocabulary(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user: User = Depends(get_current_user),
    ):

        items = service.list_vocabulary(user.id, limit, offset)

        return [VocabularyResponse.from_domain(i) for i in items]


    @router.post("/{item_id}/review", response_model=VocabularyResponse)
    def review_item(
        item_id: int,
        payload: ReviewRequest,
        user: User = Depends(get_current_user),
    ):

        if payload.rating not in REVIEW_RATINGS:
            raise HTTPException(400, "Invalid rating")

        try:

            updated = service.review_item(
                user.id,
                item_id,
                payload.rating,
            )

            return VocabularyResponse.from_domain(updated)

        except NotFoundError:

            raise HTTPException(404, "Vocabulary item not found")


    @router.get("/due", response_model=list[VocabularyResponse])
    def due_items(user: User = Depends(get_current_user)):

        items = service.list_due_items(user.id)

        return [VocabularyResponse.from_domain(i) for i in items]


    @router.get("/review-session", response_model=list[VocabularyResponse])
    def review_session(user: User = Depends(get_current_user)):

        items = service.review_session(user.id)

        return [VocabularyResponse.from_domain(i) for i in items]


    # ----------------------------------------
    # NEW: extract vocabulary from text
    # ----------------------------------------

    @router.post("/extract", response_model=list[VocabularyResponse])
    def extract_vocabulary(
        text: str,
        source_lang: str,
        target_lang: str,
        user: User = Depends(get_current_user),
    ):

        items = service.process_ocr_text(
            user.id,
            text,
            source_lang,
            target_lang,
        )

        return [VocabularyResponse.from_domain(i) for i in items]

    return router