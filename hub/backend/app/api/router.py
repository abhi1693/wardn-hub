from fastapi import APIRouter

from app.modules.health.router import router as health_router
from app.modules.registry.router import admin_router as registry_admin_router
from app.modules.registry.router import public_router as registry_public_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(registry_public_router)
api_router.include_router(registry_admin_router)

