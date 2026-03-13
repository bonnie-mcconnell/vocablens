from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from vocablens.auth.jwt import decode_token
from vocablens.domain.user import User
from vocablens.infrastructure.db.session import get_session
from vocablens.infrastructure.postgres_user_repository import PostgresUserRepository
from vocablens.infrastructure.repositories_users import SQLiteUserRepository

security = HTTPBearer()


async def get_user_repo(
    session=Depends(get_session),
):
    # prefer Postgres; fallback to SQLite if session not available
    if session:
        return PostgresUserRepository(session)
    return SQLiteUserRepository("vocablens.db")


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

    user = user_repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user
