import os

TEST_SETTINGS = {
    "WARDN_HUB_ENVIRONMENT": "local",
    "WARDN_HUB_API_PREFIX": "/api/v1",
    "WARDN_HUB_LOG_LEVEL": "INFO",
    "WARDN_HUB_API_TOKEN_SECRET": "test-token-secret",
    "WARDN_HUB_API_TOKEN_PREFIX": "wardn_hub",
    "WARDN_HUB_SESSION_COOKIE_NAME": "wardn_hub_session",
    "WARDN_HUB_SESSION_SECRET": "test-session-secret",
    "WARDN_HUB_SESSION_TTL_SECONDS": "43200",
    "WARDN_HUB_REGISTRY_PUBLIC_BASE_URL": "http://localhost:3000",
    "WARDN_HUB_DATABASE_URL": "postgresql+asyncpg://user:pass@localhost:5432/wardn_hub",
}


for key, value in TEST_SETTINGS.items():
    os.environ.setdefault(key, value)
