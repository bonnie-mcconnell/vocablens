from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from vocablens.config.settings import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionMaker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_session() -> AsyncSession:
    async with AsyncSessionMaker() as session:
        yield session
