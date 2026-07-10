from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from app.db.session import create_database_engine


async def test_create_database_engine_uses_client_pool_when_enabled() -> None:
    engine = create_database_engine(
        "postgresql+asyncpg://user:pass@localhost:5432/wardn_hub",
        client_pool_enabled=True,
    )

    try:
        assert isinstance(engine.sync_engine.pool, AsyncAdaptedQueuePool)
    finally:
        await engine.dispose()


async def test_create_database_engine_uses_null_pool_when_disabled() -> None:
    engine = create_database_engine(
        "postgresql+asyncpg://user:pass@localhost:5432/wardn_hub",
        client_pool_enabled=False,
    )

    try:
        assert isinstance(engine.sync_engine.pool, NullPool)
    finally:
        await engine.dispose()
