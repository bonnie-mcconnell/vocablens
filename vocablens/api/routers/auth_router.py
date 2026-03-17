from fastapi import APIRouter, HTTPException, Depends

from vocablens.infrastructure.postgres_user_repository import PostgresUserRepository
from vocablens.api.schemas import RegisterRequest, LoginRequest, TokenResponse

from vocablens.auth.security import hash_password, verify_password
from vocablens.auth.jwt import create_access_token

from vocablens.domain.errors import PersistenceError
from vocablens.api.dependencies import get_user_repo


DUMMY_HASH = "$2b$12$C6UzMDM.H6dfI/f/IKcEeO6cWwWlR9E9QnUnxE27XGr0CcsMEY0p6"


def create_auth_router() -> APIRouter:

    router = APIRouter(prefix="/auth", tags=["Authentication"])

    @router.post("/register", response_model=TokenResponse)
    async def register(
        payload: RegisterRequest,
        user_repo: PostgresUserRepository = Depends(get_user_repo),
    ):

        hashed = hash_password(payload.password)

        try:
            user = await user_repo.create(
                email=payload.email,
                password_hash=hashed,
            )

        except PersistenceError:
            raise HTTPException(
                status_code=400,
                detail="Email already registered",
            )

        token = create_access_token(user.id)

        return TokenResponse(access_token=token)

    @router.post("/login", response_model=TokenResponse)
    async def login(
        payload: LoginRequest,
        user_repo: PostgresUserRepository = Depends(get_user_repo),
    ):

        user = await user_repo.get_by_email(payload.email)

        if not user:
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

    return router
