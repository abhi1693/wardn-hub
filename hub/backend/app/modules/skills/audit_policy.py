import hashlib
import json
import os

from app.core.codex import (
    CODEX_APP_SERVER_URL_ENV,
    CODEX_CHAT_COMPLETIONS_BRIDGE_VERSION,
    CODEX_LLM_MODEL,
    CODEX_LLM_PROVIDER,
)
from app.core.config import get_settings

SCANNER_DISTRIBUTION = "cisco-ai-skill-scanner"
SCANNER_NAME = "Cisco AI Skill Scanner"
SCANNER_VERSION = "2.0.12"
SCANNER_POLICY = "balanced"
SCANNER_BEHAVIORAL_ENABLED = True
AUDIT_NORMALIZER_VERSION = 2


def audit_configuration_hash(
    *,
    llm_enabled: bool,
    llm_provider: str = "",
    llm_model: str = "",
    llm_base_url: str = "",
    llm_api_version: str = "",
    llm_temperature: str = "",
) -> str:
    llm_configuration = {
        "enabled": llm_enabled,
        "provider": llm_provider.strip() if llm_enabled else "",
        "model": llm_model.strip() if llm_enabled else "",
        "baseUrl": llm_base_url.strip() if llm_enabled else "",
        "apiVersion": llm_api_version.strip() if llm_enabled else "",
        "temperature": llm_temperature.strip() if llm_enabled else "",
    }
    return hashlib.sha256(
        json.dumps(
            {
                "distribution": SCANNER_DISTRIBUTION,
                "version": SCANNER_VERSION,
                "policy": SCANNER_POLICY,
                "behavioral": SCANNER_BEHAVIORAL_ENABLED,
                "llm": llm_configuration,
                "normalizerVersion": AUDIT_NORMALIZER_VERSION,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def current_audit_configuration_hash(*, codex_app_server_url: str | None = None) -> str:
    llm_enabled = get_settings().skill_audit_llm_enabled
    return audit_configuration_hash(
        llm_enabled=llm_enabled,
        llm_provider=CODEX_LLM_PROVIDER,
        llm_model=CODEX_LLM_MODEL,
        llm_base_url=(codex_app_server_url or os.getenv(CODEX_APP_SERVER_URL_ENV, "")),
        llm_api_version=CODEX_CHAT_COMPLETIONS_BRIDGE_VERSION,
    )
