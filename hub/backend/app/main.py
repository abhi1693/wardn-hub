from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.api.router import api_router
from app.core.cache import ValkeyByteCache
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import (
    FixedWindowValkeyRateLimiter,
    PublicAPIRateLimitMiddleware,
    SkillTelemetryRateLimitMiddleware,
)
from app.core.telemetry import configure_telemetry
from app.modules.mcp_registry_v01.router import router as mcp_registry_v01_router
from app.modules.metrics.router import router as metrics_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    try:
        yield
    finally:
        for resource in getattr(app.state, "managed_valkey_resources", []):
            await resource.close()


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

    rate_limiter = FixedWindowValkeyRateLimiter.from_settings(settings)
    managed_valkey_resources = []
    if rate_limiter is not None:
        app.state.public_rate_limiter = rate_limiter
        telemetry_rate_limiter = FixedWindowValkeyRateLimiter.from_settings(
            settings,
            limit=settings.skill_telemetry_rate_limit_requests,
            window_seconds=settings.skill_telemetry_rate_limit_window_seconds,
            key_prefix=settings.skill_telemetry_rate_limit_key_prefix,
            client=rate_limiter.client,
        )
        app.state.skill_telemetry_rate_limiter = telemetry_rate_limiter
        managed_valkey_resources.append(rate_limiter)
        app.add_middleware(
            PublicAPIRateLimitMiddleware,
            settings=settings,
            limiter=rate_limiter,
        )
        app.add_middleware(
            SkillTelemetryRateLimitMiddleware,
            settings=settings,
            limiter=telemetry_rate_limiter,
        )

    app.state.cache = None
    if settings.cache_enabled:
        cache = ValkeyByteCache.from_settings(settings)
        app.state.cache = cache
        managed_valkey_resources.append(cache)
    app.state.managed_valkey_resources = managed_valkey_resources

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
