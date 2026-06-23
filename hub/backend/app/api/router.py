from fastapi import APIRouter

from app.modules.health.router import router as health_router
from app.modules.organizations.router import router as organizations_router
from app.modules.registry.router import admin_router as registry_admin_router
from app.modules.registry.router import public_router as registry_public_router
from app.modules.users.auth_router import router as auth_router
from app.modules.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(registry_public_router)
api_router.include_router(registry_admin_router)
