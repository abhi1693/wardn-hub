import pytest

from app.modules.registry.schemas import RegistryServerVersionCreate


def registry_payload(**overrides):
    payload = {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.github.example/weather",
        "title": "Weather",
        "description": "Weather tools for forecasts",
        "version": "1.0.0",
        "websiteUrl": "https://example.com/weather",
        "packages": [
            {
                "registryType": "npm",
                "identifier": "@example/weather-mcp",
                "version": "1.0.0",
                "transport": {"type": "stdio"},
            }
        ],
        "_meta": {
            "io.modelcontextprotocol.registry/publisher-provided": {"category": "weather"}
        },
    }
    payload.update(overrides)
    return payload


def test_mcp_server_document_preserves_aliases_and_meta() -> None:
    payload = RegistryServerVersionCreate(**registry_payload())

    serialized = payload.model_dump(by_alias=True, exclude_none=True)

    assert serialized["$schema"].endswith("/server.schema.json")
    assert serialized["websiteUrl"] == "https://example.com/weather"
    assert serialized["_meta"]["io.modelcontextprotocol.registry/publisher-provided"] == {
        "category": "weather"
    }


def test_mcpb_packages_are_allowed_in_hub() -> None:
    payload = RegistryServerVersionCreate(
        **registry_payload(
            packages=[
                {
                    "registryType": "mcpb",
                    "identifier": "example.mcpb",
                    "version": "1.0.0",
                }
            ]
        )
    )

    assert payload.packages[0]["registryType"] == "mcpb"


def test_server_definition_requires_package_or_remote_target() -> None:
    with pytest.raises(ValueError, match="at least one package or remote"):
        RegistryServerVersionCreate(**registry_payload(packages=[], remotes=[]))


def test_server_name_requires_namespace() -> None:
    with pytest.raises(ValueError):
        RegistryServerVersionCreate(**registry_payload(name="weather"))


def test_server_version_requires_semver() -> None:
    with pytest.raises(ValueError):
        RegistryServerVersionCreate(**registry_payload(version="latest"))
