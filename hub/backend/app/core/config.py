from functools import lru_cache
from typing import ClassVar

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "Wardn Hub API"
APP_VERSION = "0.1.0"


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
    session_cookie_name: str
    session_secret: str
    session_ttl_seconds: int
    registry_public_base_url: str
    database_url: str
    cors_origins: list[str] = []

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
