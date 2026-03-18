from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks

from vocablens.services.vocabulary_service import VocabularyService
from vocablens.api.schemas import VocabularyResponse, ReviewRequest
from vocablens.api.dependencies import get_current_user, get_vocabulary_service
from vocablens.domain.errors import NotFoundError
from vocablens.domain.user import User
from vocablens.core.constants import REVIEW_RATINGS


def create_vocabulary_router() -> APIRouter:

    router = APIRouter(prefix="/vocab", tags=["Vocabulary"])

    @router.get("/", response_model=list[VocabularyResponse])
    async def list_vocabulary(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user: User = Depends(get_current_user),
        service: VocabularyService = Depends(get_vocabulary_service),
    ):

        items = await service.list_vocabulary(user.id, limit, offset)

        return [VocabularyResponse.from_domain(i) for i in items]


    @router.post("/{item_id}/review", response_model=VocabularyResponse)
    async def review_item(
        item_id: int,
        payload: ReviewRequest,
        user: User = Depends(get_current_user),
        service: VocabularyService = Depends(get_vocabulary_service),
    ):

        if payload.rating not in REVIEW_RATINGS:
            raise HTTPException(400, "Invalid rating")

        try:

            updated = await service.review_item(
                user.id,
                item_id,
                payload.rating,
            )

            return VocabularyResponse.from_domain(updated)

        except NotFoundError:

            raise HTTPException(404, "Vocabulary item not found")


    @router.get("/due", response_model=list[VocabularyResponse])
    async def due_items(
        user: User = Depends(get_current_user),
        service: VocabularyService = Depends(get_vocabulary_service),
    ):

        items = await service.list_due_items(user.id)

        return [VocabularyResponse.from_domain(i) for i in items]


    @router.get("/review-session", response_model=list[VocabularyResponse])
    async def review_session(
        user: User = Depends(get_current_user),
        service: VocabularyService = Depends(get_vocabulary_service),
    ):

        items = await service.review_session(user.id)

        return [VocabularyResponse.from_domain(i) for i in items]


    @router.post("/extract", response_model=list[VocabularyResponse])
    async def extract_vocabulary(
        text: Annotated[str, Query(min_length=1, max_length=5000)],
        source_lang: Annotated[str, Query(min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")],
        target_lang: Annotated[str, Query(min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")],
        user: User = Depends(get_current_user),
        service: VocabularyService = Depends(get_vocabulary_service),
    ):

        items = await service.process_ocr_text(
            user.id,
            text,
            source_lang,
            target_lang,
        )

        return [VocabularyResponse.from_domain(i) for i in items]
    

    @router.post("/extract-async")
    def extract_vocabulary_async(
        text: Annotated[str, Query(min_length=1, max_length=5000)],
        target_lang: Annotated[str, Query(min_length=2, max_length=10, pattern=r"^[A-Za-z-]+$")],
        background_tasks: BackgroundTasks,
        user: User = Depends(get_current_user),
        service: VocabularyService = Depends(get_vocabulary_service),
    ):

        background_tasks.add_task(
            service.process_ocr_text,
            user.id,
            text,
            None,
            target_lang,
        )

        return {"status": "processing"}

    return router
