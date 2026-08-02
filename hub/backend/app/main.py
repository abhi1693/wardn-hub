from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.router import api_router
from app.core.cache import RedisSDKByteCache
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import (
    PublicAPIRateLimitMiddleware,
    SkillTelemetryRateLimitMiddleware,
)
from app.core.redis_sdk import RedisSDKResources
from app.core.telemetry import configure_telemetry
from app.modules.mcp_registry_v01.router import router as mcp_registry_v01_router
from app.modules.metrics.router import router as metrics_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    try:
        yield
    finally:
        redis_resources = getattr(app.state, "redis_sdk_resources", None)
        if redis_resources is not None:
            await redis_resources.close()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.get("/docs", include_in_schema=False)
    async def docs_redirect() -> RedirectResponse:
        return RedirectResponse(f"{settings.api_prefix}/docs")

    @app.get("/redoc", include_in_schema=False)
    async def redoc_redirect() -> RedirectResponse:
        return RedirectResponse(f"{settings.api_prefix}/redoc")

    redis_resources = RedisSDKResources.from_settings(settings)
    app.state.redis_sdk_resources = redis_resources
    if redis_resources.rate_limit_backend is not None:
        app.state.rate_limit_backend = redis_resources.rate_limit_backend
        app.add_middleware(
            PublicAPIRateLimitMiddleware,
            settings=settings,
            backend=redis_resources.rate_limit_backend,
        )
        app.add_middleware(
            SkillTelemetryRateLimitMiddleware,
            settings=settings,
            backend=redis_resources.rate_limit_backend,
        )

    app.state.cache = None
    if redis_resources.cache_backend is not None:
        app.state.cache = RedisSDKByteCache(
            backend_factory=lambda: redis_resources.cache_backend,
            default_ttl_seconds=settings.cache_default_ttl_seconds,
            max_value_bytes=settings.cache_max_value_bytes,
            eviction_group="skill-search",
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(mcp_registry_v01_router)
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(metrics_router)
    configure_telemetry(app)
    return app


app = create_app()
