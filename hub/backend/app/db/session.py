from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def create_database_engine(
    database_url: str,
    *,
    client_pool_enabled: bool,
) -> AsyncEngine:
    if client_pool_enabled:
        return create_async_engine(database_url, pool_pre_ping=True)
    return create_async_engine(database_url, poolclass=NullPool)


settings = get_settings()

engine = create_database_engine(
    settings.database_url,
    client_pool_enabled=settings.database_client_pool_enabled,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
