import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vocablens.infrastructure.db.models import UserORM
from vocablens.domain.user import User


def _map_user(row: UserORM) -> User:
    return User(
        id=row.id,
        email=row.email,
        password_hash=row.password_hash,
        created_at=row.created_at,
    )


class PostgresUserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _run(self, coro):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)  # type: ignore

    async def create(self, email: str, password_hash: str) -> User:
        obj = UserORM(email=email.strip().lower(), password_hash=password_hash)
        self.session.add(obj)
        await self.session.commit()
        await self.session.refresh(obj)
        return _map_user(obj)

    async def get_by_email(self, email: str):
        result = await self.session.execute(
            select(UserORM).where(UserORM.email == email.strip().lower())
        )
        row = result.scalar_one_or_none()
        return _map_user(row) if row else None

    async def get_by_id(self, user_id: int):
        result = await self.session.execute(
            select(UserORM).where(UserORM.id == user_id)
        )
        row = result.scalar_one_or_none()
        return _map_user(row) if row else None

    # sync wrappers removed
