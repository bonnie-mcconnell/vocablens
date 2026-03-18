import asyncio

from vocablens.core.time import utc_now
from vocablens.domain.user import User


def run_async(coro):
    return asyncio.run(coro)


def make_user(user_id: int = 1, email: str = "test@example.com") -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="hashed-password",
        created_at=utc_now(),
    )
