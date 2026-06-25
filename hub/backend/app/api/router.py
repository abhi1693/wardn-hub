from fastapi import APIRouter

from app.modules.audit.router import router as audit_router
from app.modules.health.router import router as health_router
from app.modules.organizations.router import router as organizations_router
from app.modules.partners.router import router as partners_router
from app.modules.registry.router import admin_router as registry_admin_router
from app.modules.registry.router import categories_router as registry_categories_router
from app.modules.registry.router import public_router as registry_public_router
from app.modules.registry.router import users_router as registry_users_router
from app.modules.submissions.router import router as submissions_router
from app.modules.users.auth_router import router as auth_router
from app.modules.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(partners_router)
api_router.include_router(submissions_router)
api_router.include_router(audit_router)
api_router.include_router(registry_categories_router)
api_router.include_router(registry_users_router)
api_router.include_router(registry_public_router)
api_router.include_router(registry_admin_router)
