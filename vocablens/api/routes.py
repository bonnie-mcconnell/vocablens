from fastapi import (
    APIRouter,
    UploadFile,
    File,
    HTTPException,
    Depends,
    Query,
)
import logging

from vocablens.services.vocabulary_service import VocabularyService
from vocablens.services.ocr_service import OCRService
from vocablens.api.schemas import (
    VocabularyResponse,
    TranslationRequest,
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    ReviewRequest,
)
from vocablens.domain.errors import NotFoundError
from vocablens.api.dependencies import get_current_user
from vocablens.domain.user import User
from vocablens.infrastructure.repositories_users import SQLiteUserRepository
from vocablens.auth.security import hash_password, verify_password
from vocablens.auth.jwt import create_access_token

logger = logging.getLogger(__name__)

# Dummy bcrypt hash for timing attack mitigation
DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO6cWwWlR9E9QnUnxE27XGr0CcsMEY0p6"


def create_routes(
    service: VocabularyService,
    ocr_service: OCRService,
    user_repo: SQLiteUserRepository,
) -> APIRouter:

    router = APIRouter()

    # ==========================================================
    # AUTH ROUTES
    # ==========================================================

    auth_router = APIRouter(prefix="/auth", tags=["Authentication"])

    @auth_router.post("/register", response_model=TokenResponse)
    def register(payload: RegisterRequest):
        hashed = hash_password(payload.password)

        try:
            user = user_repo.create(
                email=payload.email,
                password_hash=hashed,
            )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Email already registered",
            )

        token = create_access_token(user.id)
        return TokenResponse(access_token=token)

    @auth_router.post("/login", response_model=TokenResponse)
    def login(payload: LoginRequest):
        user = user_repo.get_by_email(payload.email)

        if not user:
            # timing attack mitigation
            verify_password(payload.password, DUMMY_HASH)
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
            )

        if not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
            )

        token = create_access_token(user.id)
        return TokenResponse(access_token=token)

    router.include_router(auth_router)

    # ==========================================================
    # TRANSLATION ROUTES
    # ==========================================================

    translate_router = APIRouter(prefix="/translate", tags=["Translation"])

    @translate_router.post("/", response_model=VocabularyResponse)
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

    @translate_router.post("/image", response_model=VocabularyResponse)
    async def translate_image(
        file: UploadFile = File(...),
        source_lang: str = Query("auto"),
        target_lang: str = Query("en"),
        user: User = Depends(get_current_user),
    ):

        image_bytes = await file.read()

        if len(image_bytes) > 5_000_000:
            raise HTTPException(
                status_code=400,
                detail="File too large (max 5MB)",
            )

        extracted_text = ocr_service.extract(image_bytes)

        if not extracted_text.strip():
            raise HTTPException(
                status_code=400,
                detail="No text detected in image",
            )

        if len(extracted_text) > 5000:
            raise HTTPException(
                status_code=400,
                detail="Text too long",
            )

        item = service.process_text(
            user.id,
            extracted_text,
            source_lang,
            target_lang,
        )

        return VocabularyResponse.from_domain(item)
    
    router.include_router(translate_router)

    # ==========================================================
    # VOCABULARY ROUTES
    # ==========================================================

    vocab_router = APIRouter(prefix="/vocab", tags=["Vocabulary"])

    @vocab_router.get("/", response_model=list[VocabularyResponse])
    def list_vocabulary(
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user: User = Depends(get_current_user),
    ):
        items = service.list_vocabulary(user.id, limit, offset)
        return [VocabularyResponse.from_domain(i) for i in items]

    @vocab_router.post("/{item_id}/review", response_model=VocabularyResponse)
    def review_item(
        item_id: int,
        payload: ReviewRequest,
        user: User = Depends(get_current_user),
    ):
        try:
            updated = service.review_item(
                user.id,
                item_id,
                payload.rating,
            )

            return VocabularyResponse.from_domain(updated)

        except NotFoundError:
            raise HTTPException(
                status_code=404,
                detail="Vocabulary item not found",
            )

    @vocab_router.get("/due", response_model=list[VocabularyResponse])
    def due_items(
        user: User = Depends(get_current_user),
    ):
        items = service.list_due_items(user.id)
        return [VocabularyResponse.from_domain(i) for i in items]

    router.include_router(vocab_router)

    return router