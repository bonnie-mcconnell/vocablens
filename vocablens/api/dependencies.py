from pathlib import Path
from functools import lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from vocablens.auth.jwt import decode_token
from vocablens.domain.user import User
from vocablens.infrastructure.repositories_users import SQLiteUserRepository

security = HTTPBearer()


@lru_cache
def get_user_repo() -> SQLiteUserRepository:
    """
    Provide a singleton user repository instance for DI.
    """
    db_path = Path("vocablens.db")
    return SQLiteUserRepository(db_path)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    user_repo: SQLiteUserRepository = Depends(get_user_repo),
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
