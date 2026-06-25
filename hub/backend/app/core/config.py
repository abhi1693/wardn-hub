from functools import lru_cache
from typing import ClassVar

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "Wardn Hub API"
APP_VERSION = "0.1.0"
LOCAL_ENVIRONMENTS = {"local", "test"}
INSECURE_SECRET_VALUES = {"change-me", "changeme", "secret", "password"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WARDN_HUB_",
        case_sensitive=False,
        extra="ignore",
        enable_decoding=False,
    )

    app_name: ClassVar[str] = APP_NAME
    app_version: ClassVar[str] = APP_VERSION
    environment: str
    api_prefix: str
    log_level: str
    api_token_secret: str
    api_token_prefix: str
    auth_providers: list[str] = ["local"]
    auth_default_provider: str = "local"
    clerk_issuer: str = ""
    clerk_jwks_url: str = ""
    clerk_audience: str = ""
    clerk_secret_key: str = ""
    session_cookie_name: str
    session_secret: str
    session_ttl_seconds: int
    registry_public_base_url: str
    database_url: str
    cors_origins: list[str] = []

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("api_prefix must start with /")
        if len(value) > 1 and value.endswith("/"):
            raise ValueError("api_prefix must not end with /")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("auth_providers", mode="before")
    @classmethod
    def parse_auth_providers(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [provider.strip().lower() for provider in value.split(",") if provider.strip()]
        return [provider.strip().lower() for provider in value]

    @field_validator("auth_default_provider")
    @classmethod
    def normalize_auth_default_provider(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("session_ttl_seconds")
    @classmethod
    def validate_session_ttl_seconds(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        return value

    @model_validator(mode="after")
    def validate_release_settings(self) -> "Settings":
        if self.environment in LOCAL_ENVIRONMENTS:
            self.validate_auth_provider_settings()
            return self

        self.validate_auth_provider_settings()
        for field_name in ("session_secret", "api_token_secret"):
            secret = getattr(self, field_name)
            if secret.lower() in INSECURE_SECRET_VALUES or len(secret) < 32:
                raise ValueError(
                    f"{field_name} must be at least 32 characters and not a placeholder "
                    "outside local/test environments"
                )

        if "*" in self.cors_origins:
            raise ValueError("cors_origins cannot contain * outside local/test environments")

        return self

    def validate_auth_provider_settings(self) -> None:
        supported_providers = {"local", "clerk"}
        unknown_providers = sorted(set(self.auth_providers) - supported_providers)
        if unknown_providers:
            raise ValueError(f"unsupported auth provider: {', '.join(unknown_providers)}")
        if not self.auth_providers:
            raise ValueError("auth_providers must include at least one provider")
        if self.auth_default_provider not in self.auth_providers:
            raise ValueError("auth_default_provider must be enabled in auth_providers")
        if "clerk" in self.auth_providers and self.environment not in LOCAL_ENVIRONMENTS:
            if not self.clerk_issuer:
                raise ValueError("clerk_issuer is required when Clerk auth is enabled")


@lru_cache
def get_settings() -> Settings:
    return Settings()
