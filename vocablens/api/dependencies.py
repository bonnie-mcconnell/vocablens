from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from vocablens.auth.jwt import decode_token
from vocablens.domain.user import User
from vocablens.infrastructure.db.session import AsyncSessionMaker
from vocablens.infrastructure.postgres_user_repository import PostgresUserRepository

security = HTTPBearer()


async def get_user_repo():
    return PostgresUserRepository(AsyncSessionMaker)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_repo=Depends(get_user_repo),
) -> User:

    try:
        user_id = decode_token(credentials.credentials)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication",
        )

    user = await user_repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user
